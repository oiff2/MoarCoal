"""Tests: `use`, Zykluserkennung und das Modul Steuerjahr (Anlage N 2025) über `evaluate(...)`."""

import datetime
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_n import (
    FIELDS_2025,
    N_EQUIPMENT,
    N_WORKPLACE_DAYS,
    N_WORKPLACE_DISTANCE,
    Direction,
    FormField,
    Rounding,
    round_for_field,
)
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import FirstWorkplace, UserInput, WorkEquipment
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import EntryAddress
from moarcoal.values.calculation import Calculation, Missing
from moarcoal.values.catalog import CatalogEntry, TimeKind, UnknownValueKey, ValueDefinition
from moarcoal.values.engine import ContractViolation, evaluate
from moarcoal.values.findings import CYCLE, Severity
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    NotYetComputable,
    Period,
    Unit,
    UserInputLocator,
    ValueKey,
    ValueLocator,
)

WORK_EQUIPMENT = ValueKey("work.equipment")

PORT = 4711
YEAR = Period.year(2025)


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


def workplace(workdays: int = 180, distance_km: int = 12) -> FirstWorkplace:
    return FirstWorkplace(
        owner="anna", year=2025, workdays=workdays, distance_km=distance_km, description="Büro"
    )


def lamp(cents: int = 4990) -> WorkEquipment:
    return WorkEquipment(
        owner="anna",
        year=2025,
        input=UserInput(
            amount_cents=cents, date=datetime.date(2025, 3, 14), description="Schreibtischlampe"
        ),
    )


# --- Steuerjahr ordnet Werte der Anlage N zu --------------------------------------------------


def test_fields_show_the_captured_inputs_through_use_with_chain() -> None:
    place = workplace()
    values = evaluate([WORK, TAX_YEAR], [place, lamp()])

    days = exposed(values.get(N_WORKPLACE_DAYS, "anna", YEAR))
    km = exposed(values.get(N_WORKPLACE_DISTANCE, "anna", YEAR))
    equipment = exposed(values.get(N_EQUIPMENT, "anna", YEAR))

    assert days.amount == Amount.of(180, Unit.DAYS)
    assert km.amount == Amount.of(12, Unit.KM)
    assert equipment.amount == Amount.eur_cents(5000)  # 49,90 € als Ausgabe aufgerundet
    (item,) = days.items
    assert isinstance(item.locator, ValueLocator)
    assert item.locator.value.key == "work.workdays"
    # Die Kette: der Posten des Arbeit-Werts ist die Nutzereingabe, erreichbar über die Fundstelle.
    assert [i.locator.entry_address for i in item.locator.value.items] == [place.address]
    assert days.backing is Backing.ASSUMED  # geerbt vom schwächsten Belegstand
    assert [s.kind for s in days.workings.steps] == ["item", "step"]


# --- Runden der Felder -------------------------------------------------------------------------


def test_equipment_is_rounded_up_with_a_step_and_work_stays_exact() -> None:
    values = evaluate([WORK, TAX_YEAR], [workplace(), lamp(8640)])

    field = exposed(values.get(N_EQUIPMENT, "anna", YEAR))
    work = exposed(values.get(WORK_EQUIPMENT, "anna", YEAR))

    assert field.amount == Amount.of(87, Unit.EUR)
    assert field.workings.steps[-1].text == "86,40 € → 87 € (aufgerundet, Ausgabe)"
    assert field.workings.steps[-1].amount == Amount.of(87, Unit.EUR)
    assert work.amount == Amount.eur_cents(8640)


def test_field_that_already_fits_gets_no_rounding_step() -> None:
    values = evaluate([WORK, TAX_YEAR], [workplace(), lamp(8700)])

    field = exposed(values.get(N_EQUIPMENT, "anna", YEAR))

    assert [s.kind for s in field.workings.steps] == ["item", "step"]


@pytest.mark.parametrize("value", ["12.4", "12.9"])
def test_km_are_rounded_down_to_whole_km(value: str) -> None:
    calculation = Calculation(None, None, YEAR, None)  # type: ignore[arg-type]
    (field,) = [f for f in FIELDS_2025 if f.key == N_WORKPLACE_DISTANCE]

    rounded = round_for_field(calculation, field, Amount(Decimal(value), Unit.KM))

    assert rounded == Amount.of(12, Unit.KM)
    assert calculation.steps[0].text.endswith("→ 12 km (auf volle km abgerundet)")


def test_income_field_rounds_down_and_cent_field_stays_exact() -> None:
    income = FormField(
        ValueKey("demo.income"), None, "1", "Erstattung", Unit.EUR, Rounding.WHOLE_EUROS,
        Direction.INCOME,
    )  # fmt: skip
    cents = FormField(ValueKey("demo.tax"), None, "2", "Lohnsteuer", Unit.EUR, Rounding.EURO_CENTS)
    calculation = Calculation(None, None, YEAR, None)  # type: ignore[arg-type]

    down = round_for_field(calculation, income, Amount(Decimal("86.60"), Unit.EUR))
    exact = round_for_field(calculation, cents, Amount(Decimal("86.60"), Unit.EUR))

    assert down == Amount.of(86, Unit.EUR)
    assert calculation.steps[0].text == "86,60 € → 86 € (abgerundet, Einnahme)"
    assert exact == Amount(Decimal("86.60"), Unit.EUR)
    assert len(calculation.steps) == 1


def test_euro_field_needs_a_direction_exactly_when_it_takes_whole_euros() -> None:
    with pytest.raises(ValueError, match="Richtung"):
        FormField(ValueKey("demo.x"), None, "1", "x", Unit.EUR, Rounding.WHOLE_EUROS)
    with pytest.raises(ValueError, match="Richtung"):
        FormField(
            ValueKey("demo.x"), None, "1", "x", Unit.EUR, Rounding.EURO_CENTS, Direction.EXPENSE
        )


def test_catalog_has_only_the_fields_of_the_durchstich() -> None:
    values = evaluate([WORK, TAX_YEAR], [])
    tax_keys = {e.key for e in values.catalog.entries() if e.key.module == "tax_year"}

    assert tax_keys == {f.key for f in FIELDS_2025}
    assert {f.elster_id for f in FIELDS_2025} == {"E0203503", "E0203504", "E0204403"}


def test_no_equipment_gives_a_zero_field_and_other_fields_stay_unaffected() -> None:
    values = evaluate([WORK, TAX_YEAR], [workplace()])

    result = values.get(N_EQUIPMENT, "anna", YEAR)

    assert isinstance(result, ExposedValue) and result.amount.value == 0
    assert isinstance(values.get(N_WORKPLACE_DAYS, "anna", YEAR), ExposedValue)


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


def test_without_workplace_the_fields_are_not_yet_computable() -> None:
    values = evaluate([WORK, TAX_YEAR], [])

    for key in (N_WORKPLACE_DAYS, N_WORKPLACE_DISTANCE):
        result = values.get(key, "anna", YEAR)
        assert isinstance(result, NotYetComputable)
        assert "keine erste Tätigkeitsstätte" in result.reason


def test_several_workplaces_are_not_assigned_silently() -> None:
    values = evaluate([WORK, TAX_YEAR], [workplace(), workplace(workdays=20)])

    result = values.get(N_WORKPLACE_DAYS, "anna", YEAR)

    assert isinstance(result, NotYetComputable)
    assert "2 erste Tätigkeitsstätten" in result.reason


def test_other_years_do_not_leak_into_the_field() -> None:
    values = evaluate([WORK, TAX_YEAR], [workplace()])

    result = values.get(N_WORKPLACE_DAYS, "anna", Period.year(2024))

    assert isinstance(result, NotYetComputable)


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
        calc.use("work.workdays")  # braucht ein Bezugsobjekt
        return Amount.eur_cents(0)

    values = evaluate([WORK, custom(definition("demo.top", top))], [])

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
    app = create_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_page_shows_values_with_expandable_chains(tmp_path: Path) -> None:
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

    page = http.get("/steuerjahr/anlage-n/2025")

    assert page.status_code == 200
    html = page.text
    assert "E0203503" in html and "E0203504" in html and "E0204403" in html
    assert "180 Tage" in html and "12 km" in html and "50 €" in html and "50,00 €" not in html
    assert html.count("<details>") >= 6  # je Feld aufklappbar, dazu der Posten des Arbeit-Werts
    assert "Wert work.workdays" in html
    assert "Schreibtischlampe" in html
    assert "49,90 € → 50 € (aufgerundet, Ausgabe)" in html  # Rundungsschritt im Rechenweg


def test_page_shows_whole_euro_field_without_cents_but_work_keeps_them(tmp_path: Path) -> None:
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

    html = http.get("/steuerjahr/anlage-n/2025").text

    assert '<strong class="betrag">87 €</strong>' in html
    assert "87,00 €" not in html
    assert "86,40 €" in html  # Posten des Moduls Arbeit bleibt genau


def test_page_shows_not_yet_computable_with_chain(tmp_path: Path) -> None:
    page = client(tmp_path).get("/steuerjahr/anlage-n/2025")

    assert page.status_code == 200
    assert "noch nicht berechenbar" in page.text
    assert "keine erste Tätigkeitsstätte" in page.text


def test_page_of_unknown_year_is_404_and_get_writes_nothing(tmp_path: Path) -> None:
    http = client(tmp_path)
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())

    assert http.get("/steuerjahr/anlage-n/2019").status_code == 404
    assert http.get("/steuerjahr/anlage-n/2025").status_code == 200

    assert sorted(p for p in tmp_path.rglob("*") if p.is_file()) == before
