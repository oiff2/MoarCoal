"""Tests des Contracts des Ausgewiesenen Werts, des Wertekatalogs, von `Values` und `evaluate`."""

import datetime
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules.work import REGISTRATION, FirstWorkplace, UserInput, WorkEquipment
from moarcoal.modules.work.values import DISTANCE_KM, EQUIPMENT, WORKDAYS
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import EntryAddress
from moarcoal.values.calculation import Calculation, NotYetSignal
from moarcoal.values.catalog import (
    CatalogEntry,
    CatalogError,
    TimeKind,
    UnknownValueKey,
    ValueDefinition,
)
from moarcoal.values.engine import ContractViolation, Values
from moarcoal.values.findings import DUPLICATE_LOCATOR, Finding, Severity, target_text
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    KeyDate,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    Unit,
    UserInputLocator,
    ValueKey,
    format_amount,
)
from moarcoal.values.testing import evaluate, fixed, not_applicable, not_yet

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)


def workplace(user: str = "anna", year: int = 2025, workdays: int = 180) -> FirstWorkplace:
    return FirstWorkplace(
        owner=user, year=year, workdays=workdays, distance_km=12, description="Büro"
    )


def equipment(cents: int, text: str, user: str = "anna", year: int = 2025) -> WorkEquipment:
    return WorkEquipment(
        owner=user,
        year=year,
        input=UserInput(amount_cents=cents, date=datetime.date(year, 3, 14), description=text),
    )


def exposed(result: object) -> ExposedValue:
    assert isinstance(result, ExposedValue)
    return result


def custom(*definitions: ValueDefinition, key: str = "demo") -> ModuleRegistration:
    return ModuleRegistration(
        key=key,
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        values=definitions,
    )


def definition(
    key: str,
    compute: Callable[[Calculation], Amount],
    unit: Unit = Unit.EUR,
    time_kind: TimeKind = TimeKind.PERIOD,
) -> ValueDefinition:
    return ValueDefinition(
        CatalogEntry(ValueKey(key), "Beispiel", unit, time_kind),
        compute,
    )


# --- Modul Arbeit über evaluate(...) ----------------------------------------------------------


def test_workdays_and_distance_are_values_of_the_workplace() -> None:
    place = workplace()
    values = evaluate([REGISTRATION], [place])
    subject = Subject(place.address)

    days = exposed(values.get(WORKDAYS, "anna", YEAR, subject))
    km = exposed(values.get(DISTANCE_KM, "anna", YEAR, subject))

    assert days.amount == Amount.of(180, Unit.DAYS)
    assert km.amount == Amount.of(12, Unit.KM)
    assert [i.locator for i in days.items] == [UserInputLocator(place.address)]
    assert days.backing is Backing.ASSUMED
    assert km.backing is Backing.ASSUMED
    assert [step.kind for step in days.workings.steps] == ["item", "step"]


def test_equipment_sums_purchases_of_the_year_with_a_line_item_each() -> None:
    lamp = equipment(4990, "Schreibtischlampe")
    chair = equipment(12000, "Bürostuhl")
    old = equipment(999, "Alter Stift", year=2024)
    values = evaluate([REGISTRATION], [lamp, chair, old])

    result = exposed(values.get(EQUIPMENT, "anna", YEAR))

    assert result.amount == Amount(Decimal("169.90"), Unit.EUR)
    assert {i.label for i in result.items} == {"Schreibtischlampe", "Bürostuhl"}
    assert sorted(str(i.locator.entry_address) for i in result.items) == sorted(
        [str(lamp.address), str(chair.address)]
    )
    assert all(i.amount.unit is Unit.EUR for i in result.items)
    assert result.backing is Backing.ASSUMED
    assert result.workings.steps[-1].text == "Summe der Arbeitsmittel"


def test_values_of_other_users_are_not_mixed_in() -> None:
    values = evaluate([REGISTRATION], [equipment(4990, "Lampe", user="berta")])

    assert exposed(values.get(EQUIPMENT, "anna", YEAR)).amount.value == 0
    assert exposed(values.get(EQUIPMENT, "berta", YEAR)).amount.value == Decimal("49.90")


def test_all_enumerates_the_workplaces_of_the_year() -> None:
    first, second, other_year = workplace(), workplace(workdays=20), workplace(year=2024)
    values = evaluate([REGISTRATION], [first, second, other_year])

    results = values.all(WORKDAYS, "anna", YEAR)

    assert sorted(exposed(r).amount.value for r in results) == [20, 180]
    assert values.all(WORKDAYS, "anna", Period.year(2023)) == []


def test_a_period_that_is_no_calendar_year_is_not_yet_computable() -> None:
    values = evaluate([REGISTRATION], [equipment(100, "Stift")])
    half = Period(datetime.date(2025, 1, 1), datetime.date(2025, 6, 30))

    result = values.get(EQUIPMENT, "anna", half)

    assert isinstance(result, NotYetComputable)
    assert "Kalenderjahr" in result.reason


def test_subject_without_matching_entry_is_not_yet_computable() -> None:
    ghost = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))

    result = evaluate([REGISTRATION], []).get(WORKDAYS, "anna", YEAR, ghost)

    assert isinstance(result, NotYetComputable)


# --- Unbekannter Schlüssel ist ein Programmfehler, nie eine Null ------------------------------


@pytest.mark.parametrize("key", ["work.nope", "nope.workdays", "workdays", ""])
def test_unknown_key_raises_instead_of_returning_zero(key: str) -> None:
    values = evaluate([REGISTRATION], [workplace()])

    with pytest.raises(UnknownValueKey):
        values.get(key, "anna", YEAR)
    with pytest.raises(UnknownValueKey):
        values.all(key, "anna", YEAR)


def test_catalog_lists_the_keys_of_work_with_units() -> None:
    entries = {e.key: e for e in evaluate([REGISTRATION], []).catalog.entries()}

    assert entries[WORKDAYS].unit is Unit.DAYS
    assert entries[DISTANCE_KM].unit is Unit.KM
    assert entries[EQUIPMENT].unit is Unit.EUR
    assert entries[WORKDAYS].has_subject and not entries[EQUIPMENT].has_subject
    assert all(e.time_kind is TimeKind.PERIOD and e.meaning for e in entries.values())


# --- Prüfungen von Values ---------------------------------------------------------------------


def test_unit_is_checked_against_the_catalog() -> None:
    wrong = definition("demo.money", lambda calc: Amount.of(1, Unit.KM), Unit.EUR)

    with pytest.raises(ContractViolation, match="Einheit"):
        evaluate([custom(wrong)], []).get("demo.money", "anna", YEAR)


def test_time_kind_and_subject_are_checked() -> None:
    values = evaluate([REGISTRATION], [workplace()])
    subject = Subject(workplace().address)

    with pytest.raises(ContractViolation, match="Zeitbezug"):
        values.get(EQUIPMENT, "anna", KeyDate.year_end(2025))
    with pytest.raises(ContractViolation, match="Bezugsobjekt"):
        values.get(WORKDAYS, "anna", YEAR)
    with pytest.raises(ContractViolation, match="Bezugsobjekt"):
        values.get(EQUIPMENT, "anna", YEAR, subject)
    with pytest.raises(ContractViolation):
        values.all(EQUIPMENT, "anna", YEAR)


def test_result_is_computed_once_per_values_object() -> None:
    calls: list[int] = []

    def compute(calc: Calculation) -> Amount:
        calls.append(1)
        return Amount.of(5, Unit.EUR)

    values = evaluate([custom(definition("demo.fixed", compute))], [])
    first = values.get("demo.fixed", "anna", YEAR)

    assert values.get("demo.fixed", "anna", YEAR) is first
    values.get("demo.fixed", "berta", YEAR)
    assert len(calls) == 2


def test_not_yet_and_not_applicable_are_distinct_results_with_reason() -> None:
    def missing(calc: Calculation) -> Amount:
        calc.not_yet("Beleg fehlt")

    def irrelevant(calc: Calculation) -> Amount:
        calc.not_applicable("Thema betrifft mich nicht")

    values = evaluate([custom(definition("demo.a", missing), definition("demo.b", irrelevant))], [])

    not_yet = values.get("demo.a", "anna", YEAR)
    not_applicable = values.get("demo.b", "anna", YEAR)
    assert isinstance(not_yet, NotYetComputable) and not_yet.reason == "Beleg fehlt"
    assert isinstance(not_applicable, NotApplicable) and not_applicable.reason.startswith("Thema")


def test_catalog_rejects_foreign_prefix_and_duplicate_keys() -> None:
    with pytest.raises(CatalogError, match="gehört nicht"):
        evaluate([custom(definition("other.x", lambda c: Amount.of(1, Unit.EUR)))], [])
    twice = definition("demo.x", lambda c: Amount.of(1, Unit.EUR))
    with pytest.raises(CatalogError, match="mehrfach"):
        evaluate([custom(twice, twice)], [])


def test_catalog_rejects_subject_flag_without_enumeration() -> None:
    entry = CatalogEntry(ValueKey("demo.s"), "x", Unit.EUR, TimeKind.PERIOD, has_subject=True)

    with pytest.raises(CatalogError, match="Aufzählung"):
        evaluate([custom(ValueDefinition(entry, lambda c: Amount.of(1, Unit.EUR)))], [])


def test_key_must_have_module_and_name() -> None:
    with pytest.raises(ValueError):
        ValueKey("workdays")
    assert ValueKey("work.workdays").module == "work"


def test_calculation_year_is_the_calendar_year_and_fails_for_a_key_date() -> None:
    assert Calculation(None, None, YEAR, None).year == 2025  # type: ignore[arg-type]
    with pytest.raises(NotYetSignal, match="kein Kalenderjahr"):
        _ = Calculation(None, None, KeyDate.year_end(2025), None).year  # type: ignore[arg-type]


def test_backing_is_ordered_and_follows_the_locator() -> None:
    assert Backing.PENDING < Backing.ASSUMED < Backing.PROVEN
    address = EntryAddress(kind="WorkEquipment", id="AAAAAAAAAA")
    assert UserInputLocator(address).backing is Backing.ASSUMED


def test_period_helpers() -> None:
    assert YEAR.calendar_year == 2025
    assert Period(datetime.date(2025, 1, 2), datetime.date(2025, 12, 31)).calendar_year is None
    with pytest.raises(ValueError):
        Period(datetime.date(2025, 2, 1), datetime.date(2025, 1, 1))


# --- Im Browser: Wert mit Rechenweg und Belegstand --------------------------------------------


def make_client(root: Path) -> httpx.Client:
    app = create_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_page_shows_values_with_workings_and_backing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/arbeit/erste-taetigkeitsstaette",
        data={"year": "2025", "workdays": "180", "distance_km": "12", "description": "Büro"},
        headers=ORIGIN,
    )
    client.post(
        "/arbeit/arbeitsmittel",
        data={"year": "2025", "amount": "49,90", "date": "2025-03-14", "description": "Lampe"},
        headers=ORIGIN,
    )

    html = client.get("/arbeit").text

    assert "Ausgewiesene Werte 2025" in html
    assert "180 Tage" in html and "12 km" in html and "49,90 €" in html
    assert "Belegstand: angenommen" in html
    assert "<details>" in html and "Rechenweg" in html and "Einzelposten" in html
    assert "Summe der Arbeitsmittel" in html
    assert 'href="/arbeit/arbeitsmittel/' in html  # Fundstelle verlinkt die Nutzereingabe
    assert " style=" not in html and " onclick=" not in html  # CSP verbietet Inline


def test_page_without_entries_shows_no_value_section(tmp_path: Path) -> None:
    assert "Ausgewiesene Werte" not in make_client(tmp_path).get("/arbeit").text


# --- Doppelte Fundstellen -----------------------------------------------------------------------

INPUT = UserInputLocator(EntryAddress(kind="Demo", id="7KQ2M3XA4T"))
OTHER_INPUT = UserInputLocator(EntryAddress(kind="Demo", id="6KQ2M3XA4T"))


def input_value(locator: UserInputLocator, cents: int = 100) -> Callable[[Calculation], Amount]:
    def compute(calc: Calculation) -> Amount:
        item = calc.item("Posten", Amount.eur_cents(cents), locator)
        return item.amount

    return compute


def duplicates(values: Values) -> list[Finding]:
    return [f for f in values.findings if f.kind == DUPLICATE_LOCATOR]


def test_same_locator_twice_in_one_value_is_an_error_finding_but_value_is_computed() -> None:
    def compute(calc: Calculation) -> Amount:
        calc.item("a", Amount.eur_cents(100), INPUT)
        calc.item("b", Amount.eur_cents(200), INPUT)
        return Amount.eur_cents(300)

    values = evaluate([custom(definition("demo.twice", compute))], [])

    result = values.get("demo.twice", "anna", YEAR)

    assert exposed(result).amount == Amount.eur_cents(300)
    (finding,) = duplicates(values)
    assert finding.severity is Severity.ERROR
    assert finding.target == result.ref
    assert str(INPUT.address) in finding.message


def test_same_locator_via_a_chain_is_an_error_finding() -> None:
    def top(calc: Calculation) -> Amount:
        calc.item("direkt", Amount.eur_cents(100), INPUT)
        used = calc.use("demo.base")
        assert used is not None
        return Amount.eur_cents(200)

    values = evaluate(
        [custom(definition("demo.top", top), definition("demo.base", input_value(INPUT)))], []
    )

    values.get("demo.top", "anna", YEAR)

    (finding,) = duplicates(values)
    assert target_text(finding.target).startswith("demo.top@")
    assert finding.severity is Severity.ERROR


def test_same_locator_in_two_chain_values_of_one_value_counts() -> None:
    def top(calc: Calculation) -> Amount:
        calc.use("demo.left")
        calc.use("demo.right")
        return Amount.eur_cents(200)

    values = evaluate(
        [
            custom(
                definition("demo.top", top),
                definition("demo.left", input_value(INPUT)),
                definition("demo.right", input_value(INPUT)),
            )
        ],
        [],
    )

    values.get("demo.top", "anna", YEAR)

    assert [target_text(f.target).split("@")[0] for f in duplicates(values)] == ["demo.top"]


def test_distinct_locators_give_no_finding() -> None:
    def top(calc: Calculation) -> Amount:
        calc.use("demo.left")
        calc.use("demo.right")
        calc.item("direkt", Amount.eur_cents(100), UserInputLocator(workplace().address))
        return Amount.eur_cents(300)

    values = evaluate(
        [
            custom(
                definition("demo.top", top),
                definition("demo.left", input_value(INPUT)),
                definition("demo.right", input_value(OTHER_INPUT)),
            )
        ],
        [],
    )

    values.get("demo.top", "anna", YEAR)

    assert values.findings == []


def test_duplicate_locator_shows_up_in_the_finding_list() -> None:
    def compute(calc: Calculation) -> Amount:
        calc.item("a", Amount.eur_cents(100), INPUT)
        calc.item("b", Amount.eur_cents(100), INPUT)
        return Amount.eur_cents(200)

    values = evaluate([custom(definition("demo.twice", compute))], [])

    found = values.finding_list("anna", 2025).visible

    assert [f.kind for f in found] == [DUPLICATE_LOCATOR]


# --- foreign: fremde Werte fest vorgegeben ------------------------------------------------------


def uses(key: str, subject: Subject | None = None) -> Callable[[Calculation], Amount]:
    def compute(calc: Calculation) -> Amount:
        item = calc.use(key, subject)
        return item.amount if item is not None else Amount.eur_cents(0)

    return compute


def test_foreign_value_is_used_like_a_computed_one_with_its_own_item() -> None:
    given = Amount.eur_cents(8640)
    values = evaluate(
        [custom(definition("demo.top", uses("other.money")))],
        foreign={("other.money", None, YEAR): fixed(given, Backing.PENDING)},
    )

    result = exposed(values.get("demo.top", "anna", YEAR))

    assert result.amount == given
    assert result.backing is Backing.PENDING
    (item,) = result.items
    used = item.locator.used_value
    assert used is not None and used.key == "other.money" and len(used.items) == 1


def test_foreign_not_yet_and_not_applicable_pass_on_like_real_values() -> None:
    values = evaluate(
        [custom(definition("demo.a", uses("other.a")), definition("demo.b", uses("other.b")))],
        foreign={
            ("other.a", None, YEAR): not_yet("keine Eingabe"),
            ("other.b", None, YEAR): not_applicable("abgeschaltet"),
        },
    )

    a = values.get("demo.a", "anna", YEAR)
    b = exposed(values.get("demo.b", "anna", YEAR))

    assert isinstance(a, NotYetComputable) and "keine Eingabe" in a.reason
    assert [link.key for link in a.chain] == ["other.a"]
    assert b.items == () and b.workings.steps[0].kind == "decision"


def test_foreign_subjects_come_from_the_given_keys() -> None:
    first, second = Subject(workplace().address), Subject(workplace(workdays=20).address)
    values = evaluate(
        [],
        foreign={
            ("other.days", first, YEAR): fixed(Amount.of(180, Unit.DAYS)),
            ("other.days", second, YEAR): fixed(Amount.of(20, Unit.DAYS)),
            ("other.days", first, Period.year(2024)): fixed(Amount.of(1, Unit.DAYS)),
        },
    )

    assert values.subjects("other.days", "anna", YEAR) == [first, second]
    assert values.subjects("other.days", "anna", Period.year(2023)) == []


def test_foreign_key_without_given_time_is_a_programming_error() -> None:
    values = evaluate([], foreign={("other.money", None, YEAR): fixed(Amount.eur_cents(1))})

    with pytest.raises(ContractViolation, match="keine Vorgabe"):
        values.get("other.money", "anna", Period.year(2024))


def test_key_registered_and_given_is_a_programming_error() -> None:
    with pytest.raises(ContractViolation, match="angemeldet und vorgegeben"):
        evaluate([REGISTRATION], foreign={(EQUIPMENT, None, YEAR): fixed(Amount.eur_cents(1))})


def test_key_neither_registered_nor_given_stays_unknown() -> None:
    values = evaluate([], foreign={("other.money", None, YEAR): fixed(Amount.eur_cents(1))})

    with pytest.raises(UnknownValueKey):
        values.get("other.nope", "anna", YEAR)


# --- Anzeige eines Betrags ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "whole_euros", "text"),
    [
        (Amount.eur_cents(123456), False, "1.234,56 €"),
        (Amount.eur_cents(123400), False, "1.234,00 €"),
        (Amount.eur_cents(123400), True, "1.234 €"),
        (Amount.eur_cents(8640), True, "86,40 €"),  # ungerundet: nichts abschneiden
        (Amount.eur_cents(-5), False, "-0,05 €"),
        (Amount.of(220, Unit.DAYS), False, "220 Tage"),
        (Amount(Decimal("12.40"), Unit.KM), False, "12,4 km"),
        (Amount.of(1500, Unit.KM), False, "1.500 km"),
    ],
)
def test_amounts_read_the_same_everywhere(amount: Amount, whole_euros: bool, text: str) -> None:
    assert format_amount(amount, whole_euros=whole_euros) == text


def test_duplicate_locator_fingerprint_follows_the_locator() -> None:
    def duplicate(locator: UserInputLocator) -> Finding:
        def compute(calc: Calculation) -> Amount:
            calc.item("a", Amount.eur_cents(100), locator)
            calc.item("b", Amount.eur_cents(100), locator)
            return Amount.eur_cents(200)

        values = evaluate([custom(definition("demo.twice", compute))], [])
        values.get("demo.twice", "anna", YEAR)
        (finding,) = duplicates(values)
        return finding

    assert duplicate(INPUT).fingerprint == duplicate(INPUT).fingerprint
    assert duplicate(OTHER_INPUT).fingerprint != duplicate(INPUT).fingerprint
