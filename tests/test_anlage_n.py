"""Tests: `use`, Zykluserkennung und das Modul Steuerjahr (Anlage N) über `evaluate(...)`.

Die Werte von Arbeit sind fest vorgegeben (`foreign`); nur die Seiten laufen mit dem echten Modul.
"""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import anlage_n
from moarcoal.modules.tax_year.anlage_n import (
    FIELDS_2025,
    FORMS,
    N_ABSENCE_DAYS,
    N_CAR_DISTANCE,
    N_EQUIPMENT,
    N_WORKDAYS_PER_WEEK,
    N_WORKPLACE_DAYS,
    N_WORKPLACE_DISTANCE,
    STRUCTURES,
    WORK_ABSENCE_DAYS,
    WORK_CAR_DISTANCE,
    WORK_DISTANCE_KM,
    WORK_EQUIPMENT,
    WORK_TRIP_DAYS,
    WORK_WORKDAYS,
    WORK_WORKDAYS_PER_WEEK,
)
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import EntryAddress
from moarcoal.values.calculation import Calculation, Missing
from moarcoal.values.catalog import CatalogEntry, TimeKind, UnknownValueKey, ValueDefinition
from moarcoal.values.engine import ContractViolation, Foreign
from moarcoal.values.findings import CYCLE, Finding, Severity
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    Unit,
    UserInputLocator,
    ValueKey,
    ValueLocator,
)
from moarcoal.values.testing import evaluate, fixed, not_applicable, not_yet

PORT = 4711
YEAR = Period.year(2025)
PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))
OTHER_PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="BBBBBBBBBB"))


def exposed(result: object) -> ExposedValue:
    assert isinstance(result, ExposedValue)
    return result


def custom(*definitions: ValueDefinition) -> ModuleRegistration:
    return ModuleRegistration(
        key="demo",
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        values=definitions,
    )


def definition(key: str, compute: Callable[[Calculation], Amount]) -> ValueDefinition:
    return ValueDefinition(
        CatalogEntry(ValueKey(key), "Beispiel", Unit.EUR, TimeKind.PERIOD), compute
    )


def _assumed() -> UserInputLocator:
    return UserInputLocator(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))


def place(subject: Subject = PLACE, workdays: int = 180, km: int = 12) -> Foreign:
    """Die Werte von Arbeit zu einer ersten Tätigkeitsstätte 2025."""
    return {
        (WORK_WORKDAYS, subject, YEAR): fixed(Amount.of(workdays, Unit.DAYS)),
        (WORK_DISTANCE_KM, subject, YEAR): fixed(Amount.of(km, Unit.KM)),
        **{
            (key, subject, YEAR): not_yet("keine Eingabe")
            for key in (WORK_WORKDAYS_PER_WEEK, WORK_ABSENCE_DAYS, WORK_CAR_DISTANCE)
        },
        (WORK_TRIP_DAYS, None, YEAR): not_yet("keine Dienstreisen"),
    }


def equipment(cents: int = 4990) -> Foreign:
    return {(WORK_EQUIPMENT, None, YEAR): fixed(Amount.eur_cents(cents))}


def tax_year(foreign: Foreign) -> Callable[[ValueKey, Period], object]:
    values = evaluate([TAX_YEAR], foreign=foreign)
    return lambda key, time=YEAR: values.get(key, "anna", time)


# --- Steuerjahr ordnet Werte der Anlage N zu --------------------------------------------------


def test_fields_show_the_given_inputs_through_use_with_chain() -> None:
    value = tax_year({**place(), **equipment()})

    days = exposed(value(N_WORKPLACE_DAYS, YEAR))
    km = exposed(value(N_WORKPLACE_DISTANCE, YEAR))
    stuff = exposed(value(N_EQUIPMENT, YEAR))

    assert days.amount == Amount.of(180, Unit.DAYS)
    assert km.amount == Amount.of(12, Unit.KM)
    assert stuff.amount == Amount.eur_cents(5000)  # 49,90 € als Ausgabe aufgerundet
    (item,) = days.items
    assert isinstance(item.locator, ValueLocator)
    assert item.locator.value.key == "work.workdays"
    assert item.locator.value.subject == PLACE
    assert days.backing is Backing.ASSUMED  # geerbt vom schwächsten Belegstand
    assert [s.kind for s in days.workings.steps] == ["item", "step"]


# --- Runden der Felder -------------------------------------------------------------------------


def test_equipment_is_rounded_up_with_a_step_and_the_item_stays_exact() -> None:
    field = exposed(tax_year({**place(), **equipment(8640)})(N_EQUIPMENT, YEAR))

    assert field.amount == Amount.of(87, Unit.EUR)
    assert field.workings.steps[-1].text == "86,40 € → 87 € (aufgerundet, Ausgabe)"
    assert field.workings.steps[-1].amount == Amount.of(87, Unit.EUR)
    assert field.items[0].amount == Amount.eur_cents(8640)


def test_field_that_already_fits_gets_no_rounding_step() -> None:
    field = exposed(tax_year({**place(), **equipment(8700)})(N_EQUIPMENT, YEAR))

    assert [s.kind for s in field.workings.steps] == ["item", "step"]


def test_not_yet_computable_input_passes_on_with_chain() -> None:
    def base(calc: Calculation) -> Amount:
        calc.not_yet("keine Eingabe")

    def top(calc: Calculation) -> Amount:
        item = calc.use("demo.base")
        assert item is not None
        return item.amount

    values = evaluate([custom(definition("demo.base", base), definition("demo.top", top))], [])

    result = values.get("demo.top", "anna", YEAR)

    assert isinstance(result, NotYetComputable)
    assert "keine Eingabe" in result.reason
    assert [link.key for link in result.chain] == ["demo.base"]


def test_catalog_has_every_known_field_but_values_only_for_the_computed_ones() -> None:
    values = evaluate([TAX_YEAR])
    tax_keys = {e.key for e in values.catalog.entries()}

    assert tax_keys == {f.key for f in FIELDS_2025 if f.computed}
    assert {f.elster_id for f in FIELDS_2025 if f.computed} == {
        "E0200002",
        "E0200201",
        "E0200204",
        "E0200301",
        "E0200304",
        "E0200401",
        "E0200404",
        "E0203503",
        "E0203504",
        "E0203505",
        "E0203508",
        "E0203509",
        "E0204403",
        "E0204507",
        "E0205004",
        "E0205518",
    }
    assert len(FIELDS_2025) == len({f.key for f in FIELDS_2025}) == 23
    assert len({f.elster_id for f in FIELDS_2025}) == 23
    assert {"E0200201", "E0205518", "E0204901"} <= {f.elster_id for f in FIELDS_2025}


def test_fields_without_amount_or_computation_are_marked_and_consistent() -> None:
    uncomputed = [f for f in FIELDS_2025 if not f.computed]
    no_amount = [f for f in FIELDS_2025 if f.unit is None]

    assert len(uncomputed) == 7
    assert {f.elster_id for f in no_amount} == {
        "E0203003",
        "E0203501",
        "E0203101",
        "E0204901",
        "E0205003",
    }
    assert all(not f.computed and not f.assessment for f in no_amount)


def test_equipment_that_does_not_apply_makes_the_field_not_apply_too() -> None:
    value = tax_year({**place(), (WORK_EQUIPMENT, None, YEAR): not_applicable("abgeschaltet")})

    result = value(N_EQUIPMENT, YEAR)

    assert isinstance(result, NotApplicable)
    assert isinstance(value(N_WORKPLACE_DAYS, YEAR), ExposedValue)


def test_workplace_of_another_year_does_not_count_for_the_field() -> None:
    previous = Period.year(2024)
    value = tax_year(
        {
            (WORK_WORKDAYS, PLACE, previous): fixed(Amount.of(180, Unit.DAYS)),
            (WORK_DISTANCE_KM, PLACE, previous): fixed(Amount.of(12, Unit.KM)),
            **equipment(),
        }
    )

    for key in (N_WORKPLACE_DAYS, N_WORKPLACE_DISTANCE):
        result = value(key, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "keine erste Tätigkeitsstätte" in result.reason


def test_several_workplaces_are_not_assigned_silently() -> None:
    value = tax_year({**place(), **place(OTHER_PLACE, workdays=20)})

    result = value(N_WORKPLACE_DAYS, YEAR)

    assert isinstance(result, NotYetComputable)
    assert "2 erste Tätigkeitsstätten" in result.reason


def test_year_without_catalog_is_not_yet_computable() -> None:
    value = tax_year({**place(), **equipment()})

    for key in (N_WORKPLACE_DAYS, N_WORKPLACE_DISTANCE, N_EQUIPMENT):
        result = value(key, Period.year(2024))
        assert isinstance(result, NotYetComputable)
        assert result.reason == "Anlage N 2024 deckt MoarCoal noch nicht ab"


# --- use und try_use --------------------------------------------------------------------------


def test_use_inherits_the_weakest_backing_and_amount() -> None:
    def base(calc: Calculation) -> Amount:
        calc.item("x", Amount.eur_cents(100), _assumed())
        return Amount.eur_cents(100)

    def top(calc: Calculation) -> Amount:
        item = calc.use("demo.base")
        assert item is not None
        return item.amount

    values = evaluate([custom(definition("demo.base", base), definition("demo.top", top))], [])

    result = exposed(values.get("demo.top", "anna", YEAR))

    assert result.amount == Amount.eur_cents(100)
    assert result.backing is Backing.ASSUMED
    assert result.items[0].label == "demo.base"


def test_try_use_lets_the_calculation_rule_the_gap_itself() -> None:
    def base(calc: Calculation) -> Amount:
        calc.not_yet("fehlt")

    def top(calc: Calculation) -> Amount:
        found = calc.try_use("demo.base")
        assert isinstance(found, Missing)
        calc.decide(f"Ohne demo.base gilt 0: {found.reason}")
        return Amount.eur_cents(0)

    values = evaluate([custom(definition("demo.base", base), definition("demo.top", top))], [])

    result = exposed(values.get("demo.top", "anna", YEAR))

    assert result.amount == Amount.eur_cents(0)
    assert result.workings.steps[0].kind == "decision"
    assert result.items == ()


def test_use_of_unknown_key_is_a_programming_error() -> None:
    def top(calc: Calculation) -> Amount:
        calc.use("demo.nope")
        return Amount.eur_cents(0)

    values = evaluate([custom(definition("demo.top", top))], [])

    with pytest.raises(UnknownValueKey):
        values.get("demo.top", "anna", YEAR)


def test_use_checks_unit_and_subject_like_get() -> None:
    def top(calc: Calculation) -> Amount:
        calc.use("other.per_subject")  # braucht ein Bezugsobjekt
        return Amount.eur_cents(0)

    per_subject = ValueDefinition(
        CatalogEntry(ValueKey("other.per_subject"), "Beispiel", Unit.EUR, TimeKind.PERIOD, True),
        lambda calc: Amount.eur_cents(0),
        lambda state, time: [],
    )
    other = ModuleRegistration(
        key="other", area_name="", nav_label="", nav_url="", router=APIRouter(), kinds=()
    )
    values = evaluate([custom(definition("demo.top", top)), replace(other, values=(per_subject,))])

    with pytest.raises(ContractViolation, match="Bezugsobjekt"):
        values.get("demo.top", "anna", YEAR)


# --- Zykluserkennung --------------------------------------------------------------------------


def cyclic(*names: str) -> list[ValueDefinition]:
    """Je Name ein Wert, der den nächsten verwendet; der letzte den ersten."""
    definitions: list[ValueDefinition] = []
    for index, name in enumerate(names):
        target = names[(index + 1) % len(names)]

        def compute(calc: Calculation, target: str = target) -> Amount:
            item = calc.use(target)
            assert item is not None
            return item.amount

        definitions.append(definition(name, compute))
    return definitions


def test_cycle_makes_all_members_not_yet_computable_and_gives_an_error_finding() -> None:
    values = evaluate([custom(*cyclic("demo.a", "demo.b", "demo.c"))], [])

    results = {k: values.get(k, "anna", YEAR) for k in ("demo.a", "demo.b", "demo.c")}

    assert all(isinstance(r, NotYetComputable) for r in results.values())
    (finding,) = values.findings
    assert finding.kind == CYCLE
    assert finding.severity is Severity.ERROR
    assert [r.key for r in finding.chain] == ["demo.a", "demo.b", "demo.c", "demo.a"]
    assert "demo.a → demo.b → demo.c → demo.a" in finding.message
    chain_of_a = results["demo.a"]
    assert isinstance(chain_of_a, NotYetComputable)
    assert [link.key for link in chain_of_a.chain] == ["demo.b", "demo.c", "demo.a"]


def test_value_using_a_cycle_member_is_not_yet_computable_too() -> None:
    def outside(calc: Calculation) -> Amount:
        item = calc.use("demo.a")
        assert item is not None
        return item.amount

    values = evaluate(
        [custom(*cyclic("demo.a", "demo.b"), definition("demo.outside", outside))],
        [],
    )

    result = values.get("demo.outside", "anna", YEAR)

    assert isinstance(result, NotYetComputable)
    assert len(values.findings) == 1


def test_a_value_using_itself_is_a_cycle() -> None:
    values = evaluate([custom(*cyclic("demo.a"))], [])

    assert isinstance(values.get("demo.a", "anna", YEAR), NotYetComputable)
    (finding,) = values.findings
    assert [r.key for r in finding.chain] == ["demo.a", "demo.a"]


def test_no_cycle_no_finding_and_diamond_is_no_cycle() -> None:
    def leaf(calc: Calculation) -> Amount:
        return Amount.eur_cents(1)

    def left(calc: Calculation) -> Amount:
        item = calc.use("demo.leaf")
        assert item is not None
        return item.amount

    def top(calc: Calculation) -> Amount:
        a = calc.use("demo.left")
        b = calc.use("demo.leaf")
        assert a is not None and b is not None
        return Amount.eur_cents(int((a.amount.value + b.amount.value) * 100))

    values = evaluate(
        [
            custom(
                definition("demo.leaf", leaf),
                definition("demo.left", left),
                definition("demo.top", top),
            )
        ],
        [],
    )

    assert exposed(values.get("demo.top", "anna", YEAR)).amount == Amount.eur_cents(2)
    assert values.findings == []


# --- Seite der Anlage N ------------------------------------------------------------------------


def client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_page_shows_values_with_expandable_chains(
    tmp_path: Path, anlage_n_text: Callable[[httpx.Client], str]
) -> None:
    http = client(tmp_path)
    origin = {"Origin": f"http://127.0.0.1:{PORT}"}
    http.post(
        "/arbeit/erste-taetigkeitsstaette",
        data={"year": "2025", "workdays": "180", "distance_km": "12", "description": "Büro"},
        headers=origin,
    )
    http.post(
        "/arbeit/arbeitsmittel",
        data={
            "year": "2025",
            "amount": "49,90",
            "date": "2025-03-14",
            "description": "Schreibtischlampe",
        },
        headers=origin,
    )

    html = anlage_n_text(http)

    assert "E0203503" in html and "E0203504" in html and "E0204403" in html
    assert "180 Tage" in html and "12 km" in html and "50 €" in html and "50,00 €" not in html
    assert html.count("<details>") >= 6  # je Feld aufklappbar, dazu der Posten des Arbeit-Werts
    assert "Wert work.workdays" in html
    assert "Schreibtischlampe" in html
    assert "49,90 € → 50 € (aufgerundet, Ausgabe)" in html  # Rundungsschritt im Rechenweg


def test_page_shows_whole_euro_field_without_cents_but_work_keeps_them(
    tmp_path: Path, anlage_n_text: Callable[[httpx.Client], str]
) -> None:
    http = client(tmp_path)
    origin = {"Origin": f"http://127.0.0.1:{PORT}"}
    http.post(
        "/arbeit/arbeitsmittel",
        data={
            "year": "2025",
            "amount": "86,40",
            "date": "2025-03-14",
            "description": "Schreibtischlampe",
        },
        headers=origin,
    )

    html = anlage_n_text(http)

    assert '<strong class="betrag">87 €</strong>' in html
    assert "87,00 €" not in html
    assert "86,40 €" in html  # Posten des Moduls Arbeit bleibt genau


def test_page_shows_not_yet_computable_with_chain(
    tmp_path: Path, anlage_n_text: Callable[[httpx.Client], str]
) -> None:
    text = anlage_n_text(client(tmp_path))

    assert "noch nicht berechenbar" in text
    assert "keine erste Tätigkeitsstätte" in text


def test_pages_follow_mein_elster_and_show_only_catalog_fields() -> None:
    pages = form_pages(STRUCTURES[2025], FORMS[2025])

    assert [p.slug for p in pages][:2] == ["1", "8"]
    assert len({p.slug for p in pages}) == len(pages)
    shown = [row.field.elster_id for p in pages for row in p.rows]
    assert sorted(str(e) for e in shown) == sorted(str(f.elster_id) for f in FORMS[2025])
    first = pages[0].rows
    assert first[0].headings == () and first[1].headings != ()
    assert first[1].headings == first[2].headings or first[2].headings == ()  # Überschrift einmal


def test_each_page_has_its_own_url_with_label_line_and_e_kennung(tmp_path: Path) -> None:
    http = client(tmp_path)
    pages = form_pages(STRUCTURES[2025], FORMS[2025])

    for page in pages:
        html = http.get(f"/steuerjahr/anlage-n/2025/{page.slug}").text
        assert page.title in html
        for row in page.rows:
            assert row.field.label in html
            assert f"Nr. {row.field.form_line or '–'}, {row.field.elster_id}" in html
        other = {r.field.elster_id for p in pages if p is not page for r in p.rows}
        assert not any(str(e) in html for e in other)
    first = http.get(f"/steuerjahr/anlage-n/2025/{pages[0].slug}").text
    whole = http.get("/steuerjahr/anlage-n/2025").text
    assert whole.split("<main>", 1)[1] == first.split("<main>", 1)[1]
    assert http.get("/steuerjahr/anlage-n/2025/gibt-es-nicht").status_code == 404
    assert http.get("/steuerjahr/anlage-n/2019/1").status_code == 404


def test_page_of_unknown_year_is_404_and_get_writes_nothing(tmp_path: Path) -> None:
    http = client(tmp_path)
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())

    assert http.get("/steuerjahr/anlage-n/2019").status_code == 404
    assert http.get("/steuerjahr/anlage-n/2025").status_code == 200

    assert sorted(p for p in tmp_path.rglob("*") if p.is_file()) == before


def test_cycle_fingerprint_follows_the_members() -> None:
    def cycle(*names: str) -> Finding:
        values = evaluate([custom(*cyclic(*names))], [])
        values.get(names[0], "anna", YEAR)
        (finding,) = values.findings
        return finding

    base = cycle("demo.a", "demo.b")

    assert cycle("demo.a", "demo.b").fingerprint == base.fingerprint


# --- Nr. 28 und 31: Tage je Woche, Abwesenheit, Pkw-km -----------------------------------------


def test_workdays_per_week_and_car_distance_come_from_the_workplace() -> None:
    value = tax_year(
        {
            **place(),
            (WORK_WORKDAYS_PER_WEEK, PLACE, YEAR): fixed(Amount.of(5, Unit.DAYS)),
            (WORK_CAR_DISTANCE, PLACE, YEAR): fixed(Amount.of(Decimal("11.9"), Unit.KM)),
        }
    )

    assert exposed(value(N_WORKDAYS_PER_WEEK, YEAR)).amount == Amount.of(5, Unit.DAYS)
    km = exposed(value(N_CAR_DISTANCE, YEAR))
    assert km.amount == Amount.of(11, Unit.KM)  # abgerundet
    assert "abgerundet" in km.workings.steps[-1].text


def test_workplace_inputs_that_are_missing_are_not_yet_computable() -> None:
    value = tax_year(place())  # Arbeit liefert die Werte nicht (Eingabe fehlt)

    for key in (N_WORKDAYS_PER_WEEK, N_CAR_DISTANCE, N_ABSENCE_DAYS):
        assert not isinstance(value(key, YEAR), ExposedValue)


def absence(trip_days: int = 3, vacation: int = 30) -> Foreign:
    return {
        **place(),
        (WORK_ABSENCE_DAYS, PLACE, YEAR): fixed(Amount.of(vacation, Unit.DAYS)),
        (WORK_TRIP_DAYS, None, YEAR): fixed(Amount.of(trip_days, Unit.DAYS)),
    }


def test_absence_days_are_not_yet_computable_without_homeoffice_days() -> None:
    result = tax_year(absence())(N_ABSENCE_DAYS, YEAR)  # ohne Eingabe zu Nr. 58

    assert isinstance(result, NotYetComputable)
    assert "Homeoffice-Tage" in result.reason


def test_absence_days_sum_the_three_parts_with_working(monkeypatch: pytest.MonkeyPatch) -> None:
    def home(calculation: Calculation) -> Amount:
        return calculation.step("Homeoffice-Tage", Amount.of(20, Unit.DAYS))

    monkeypatch.setattr(anlage_n, "homeoffice_days", home)

    field = exposed(tax_year(absence())(N_ABSENCE_DAYS, YEAR))

    assert field.amount == Amount.of(53, Unit.DAYS)
    assert (
        field.workings.steps[-1].text
        == "30 Urlaubs- und Krankheitstage + 20 Homeoffice-Tage + 3 Dienstreisetage"
    )


def test_absence_days_need_the_trip_days() -> None:
    foreign = {**absence(), (WORK_TRIP_DAYS, None, YEAR): not_yet("keine Dienstreisen")}

    assert not isinstance(tax_year(foreign)(N_ABSENCE_DAYS, YEAR), ExposedValue)
