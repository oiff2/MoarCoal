"""Arbeitsmittel über der GWG-Grenze: AfA über die Nutzungsdauer (#156, nur tmp_path).

Alle Beträge und Beschreibungen sind erfunden.
"""

import datetime
import json
from decimal import Decimal
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.work import REGISTRATION, UserInput, WorkEquipment
from moarcoal.modules.work.workplace.depreciation import depreciation
from moarcoal.modules.work.workplace.entries import KINDS
from moarcoal.modules.work.workplace.values import (
    EQUIPMENT,
    EQUIPMENT_GAP,
    USEFUL_LIFE_MISSING,
)
from moarcoal.storage import Applied, Put, Rejected, open_store
from moarcoal.values.depreciation import Depreciation
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import ExposedValue, NotYetComputable, Period, UserInputLocator
from moarcoal.values.testing import evaluate

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


def purchase(
    cents: int,
    year: int = 2025,
    month: int = 3,
    life: int | None = None,
    text: str = "Schreibtisch",
) -> WorkEquipment:
    return WorkEquipment(
        owner="anna",
        year=year,
        input=UserInput(amount_cents=cents, date=datetime.date(year, month, 14), description=text),
        useful_life_years=life,
    )


def total(entries: list[WorkEquipment], year: int) -> object:
    return evaluate([REGISTRATION], entries).get(EQUIPMENT, "anna", Period.year(year))


def amount_of(result: object) -> Decimal:
    assert isinstance(result, ExposedValue), result
    return result.amount.value


def findings(entries: list[WorkEquipment], year: int, kind: str) -> list[Finding]:
    found = evaluate([REGISTRATION], entries).finding_list("anna", year).visible
    return [f for f in found if f.kind == kind]


# --- Verteilung ----------------------------------------------------------------------------


def test_desk_over_three_years_from_march_adds_up_to_the_price() -> None:
    desk = purchase(120_000, life=3)

    years = {year: amount_of(total([desk], year)) for year in range(2025, 2030)}

    assert years == {
        2025: Decimal("333.33"),  # 10 von 36 Monaten
        2026: Decimal("400.00"),
        2027: Decimal("400.00"),
        2028: Decimal("66.67"),  # die restlichen 2 Monate
        2029: Decimal("0"),
    }
    assert sum(years.values()) == Decimal("1200.00")
    assert depreciation(desk, 2025) == Depreciation(33_333, 10, 36)


def test_running_depreciation_is_a_line_item_with_workings() -> None:
    desk = purchase(120_000, year=2024, life=3)

    result = total([desk], 2025)

    assert isinstance(result, ExposedValue)
    (item,) = result.items
    assert item.label == "Schreibtisch"
    assert item.locator == UserInputLocator(desk.address)
    assert item.amount.value == Decimal("400.00")
    decision = next(s.text for s in result.workings.steps if s.kind == "decision")
    assert "1.200,00 €" in decision and "3 Jahre" in decision and "12 von 36 Monaten" in decision


def test_one_year_useful_life_counts_in_full_in_the_year_of_purchase() -> None:
    laptop = purchase(150_000, month=11, life=1, text="Notebook")

    assert amount_of(total([laptop], 2025)) == Decimal("1500.00")
    assert amount_of(total([laptop], 2026)) == Decimal("0")


def test_up_to_the_limit_counts_in_full_without_useful_life() -> None:
    chair = purchase(95_200, text="Bürostuhl")  # genau die Grenze

    assert amount_of(total([chair], 2025)) == Decimal("952.00")
    assert amount_of(total([chair], 2026)) == Decimal("0")


# --- noch nicht berechenbar ------------------------------------------------------------------


def test_above_the_limit_without_useful_life_is_not_yet_with_a_finding() -> None:
    desk = purchase(120_000, year=2024)

    for year in (2024, 2025):
        result = total([desk], year)
        assert isinstance(result, NotYetComputable)
        assert "Nutzungsdauer" in result.reason
        (finding,) = findings([desk], year, USEFUL_LIFE_MISSING)
        assert finding.severity is Severity.WARNING
        assert finding.target == desk.address
        assert finding.href == f"/arbeit/arbeitsmittel/{desk.id}"
    assert findings([desk], 2023, USEFUL_LIFE_MISSING) == []


def test_year_without_checked_limit_is_not_carried_forward() -> None:
    old = purchase(4990, year=2017, text="Lampe")  # 2017 steht nicht in der Tabelle

    result = total([old], 2017)

    assert isinstance(result, NotYetComputable)
    assert result.reason == "GWG-Grenze für 2017 noch nicht geprüft"


def test_running_depreciation_from_a_checked_year_counts_in_any_later_year() -> None:
    desk = purchase(120_000, year=2026, life=3)

    assert amount_of(total([desk], 2027)) == Decimal("400.00")


# --- Hinweis „Arbeitsmittel im Vorjahr, im Steuerjahr keine“ -----------------------------


def test_running_depreciation_counts_as_equipment_of_the_year() -> None:
    desk = purchase(120_000, year=2024, life=3)

    assert findings([desk], 2025, EQUIPMENT_GAP) == []


def test_note_comes_back_once_the_depreciation_has_ended() -> None:
    desk = purchase(120_000, year=2024, month=1, life=1)

    (note,) = findings([desk], 2025, EQUIPMENT_GAP)
    assert note.severity is Severity.NOTE


# --- Schreibweg und Bestand ----------------------------------------------------------------


def test_write_path_asks_for_useful_life_above_the_limit(tmp_path: Path) -> None:
    store = open_store(tmp_path, KINDS)

    rejected = store.apply([Put(purchase(120_000))])
    assert isinstance(rejected, Rejected)
    assert "Nutzungsdauer angeben" in str(rejected)
    assert isinstance(store.apply([Put(purchase(120_000, life=3))]), Applied)
    assert isinstance(store.apply([Put(purchase(4990, text="Lampe"))]), Applied)


def test_write_path_wants_the_date_in_the_tax_year_above_the_limit(tmp_path: Path) -> None:
    store = open_store(tmp_path, KINDS)
    december = UserInput(amount_cents=120_000, date=datetime.date(2024, 12, 1), description="Tisch")
    wrong = purchase(120_000, life=3).model_copy(update={"input": december})

    rejected = store.apply([Put(wrong)])

    assert isinstance(rejected, Rejected)
    assert "Datum der Anschaffung" in str(rejected)


def test_entries_stored_before_the_useful_life_stay_readable(tmp_path: Path) -> None:
    """Bestand ohne das Feld: lädt mit leerer Nutzungsdauer, über der Grenze mit Befund."""
    path = tmp_path / "users" / "anna" / "work" / "2025.json"
    path.parent.mkdir(parents=True)
    old = {
        "owner": "anna",
        "id": "AAAAAAAAAA",
        "year": 2025,
        "input": {"amount_cents": 120_000, "date": "2025-03-14", "description": "Schreibtisch"},
    }
    body = {"schema": "work/1", "entries": {"WorkEquipment:AAAAAAAAAA": old}}
    path.write_text(json.dumps(body), encoding="utf-8")

    store = open_store(tmp_path, KINDS)

    (entry,) = store.state().entries.values()
    assert isinstance(entry, WorkEquipment) and entry.useful_life_years is None
    assert len(findings([entry], 2025, USEFUL_LIFE_MISSING)) == 1


# --- Seite Arbeit --------------------------------------------------------------------------


def make_client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


DESK = {"year": "2024", "amount": "1200,00", "date": "2024-03-14", "description": "Schreibtisch"}


def test_page_takes_the_useful_life_and_shows_running_depreciation(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    missing = client.post("/arbeit/arbeitsmittel", data=DESK, headers=ORIGIN)
    assert missing.status_code == 409
    assert "Nutzungsdauer angeben" in missing.text
    saved = client.post(
        "/arbeit/arbeitsmittel", data=DESK | {"useful_life_years": "3"}, headers=ORIGIN
    )
    assert saved.status_code == 303

    own_year = client.get("/arbeit?jahr=2024").text
    assert "333,33 €" in own_year and "10 von 36 Monaten" in own_year
    later = client.get("/arbeit?jahr=2025").text
    assert "Laufende Abschreibungen aus Vorjahren" in later
    assert "14.03.2024" in later and "400,00 €" in later and "12 von 36 Monaten" in later
    assert "über der GWG-Grenze von 952,00 €" in later  # Hinweis am Feld Nutzungsdauer
