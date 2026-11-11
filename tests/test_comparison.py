"""Tests: Abgleich mit dem Übertragungsprotokoll und Befundliste (erfundene Werte, tmp_path)."""

import datetime
import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading
from moarcoal.modules.tax_year.anlage_n import FORMS, N_EQUIPMENT
from moarcoal.modules.tax_year.comparison import (
    AMBIGUOUS,
    DEVIATION,
    MISSING,
    UNKNOWN_ELSTER_ID,
    parse_german_number,
)
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import FirstWorkplace, UserInput, WorkEquipment
from moarcoal.storage import Document, Entry
from moarcoal.values.engine import evaluate
from moarcoal.values.findings import Finding, Severity

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
DAYS, KM = "E0203503", "E0203504"
EQUIPMENT = "E0000000"  # erfunden; Arbeitsmittel hat noch keine echte E-Kennung


def line(elster_id: str, content: str, index: str = "1_1-1-1") -> ProtocolLine:
    return ProtocolLine(
        elster_id=elster_id,
        form="N",
        form_line="",
        label="Beispiel",
        content=content,
        index=index,
        data_name=f"id-N-Beispiel-{elster_id}_usb{index}",
    )


def entries(
    lines: list[ProtocolLine], workdays: int = 220, km: int = 12, taken: int = 1, cents: int = 4990
) -> list[Entry]:
    document = Document(
        owner="anna",
        site="Belege",
        path=f"p{taken}.html",
        sha256=f"{taken:064x}",
        document_kind="transfer_protocol",
        period_start=datetime.date(2025, 1, 1),
        period_end=datetime.date(2025, 12, 31),
        taken_in_at=datetime.datetime(2026, 3, taken, tzinfo=datetime.UTC),
    )
    reading = ProtocolReading(
        owner="anna", document=document.address, year=2025, reader_version=2, lines=tuple(lines)
    )
    return [
        FirstWorkplace(
            owner="anna", year=2025, workdays=workdays, distance_km=km, description="Büro"
        ),
        WorkEquipment(
            owner="anna",
            year=2025,
            input=UserInput(amount_cents=cents, date=datetime.date(2025, 3, 14), description="x"),
        ),
        document,
        reading,
    ]


def findings(items: list[Entry]) -> list[Finding]:
    values = evaluate([WORK, TAX_YEAR], items)
    return values.finding_list("anna", 2025)


def kinds(found: list[Finding]) -> list[str]:
    return sorted(f.kind for f in found)


def test_matching_protocol_gives_only_the_unknown_elster_id_note() -> None:
    found = findings(entries([line(DAYS, "220"), line(KM, "12")]))

    assert kinds(found) == [UNKNOWN_ELSTER_ID]
    assert found[0].severity is Severity.NOTE


def test_deviation_is_a_warning_with_link_to_the_line() -> None:
    items = entries([line(DAYS, "219"), line(KM, "12")])
    found = [f for f in findings(items) if f.kind == DEVIATION]

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "220 Tage" in found[0].message and "219 Tage" in found[0].message
    reading = next(i for i in items if isinstance(i, ProtocolReading))
    assert found[0].href == (
        f"/steuerjahr/uebertragungsprotokolle/{reading.id}#id-N-Beispiel-{DAYS}_usb1_1-1-1"
    )


def test_missing_line_is_a_warning() -> None:
    found = [f for f in findings(entries([line(DAYS, "220")])) if f.kind == MISSING]

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert KM in found[0].message


@pytest.fixture
def equipment_with_elster_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arbeitsmittel hat noch keine echte E-Kennung; für den Abgleich bekommt es eine erfundene."""
    fields = tuple(
        replace(f, elster_id=EQUIPMENT) if f.key == N_EQUIPMENT else f for f in FORMS[2025]
    )
    monkeypatch.setitem(FORMS, 2025, fields)


def deviations(lines: list[ProtocolLine], cents: int = 4990, km: int = 12) -> list[Finding]:
    return [f for f in findings(entries(lines, km=km, cents=cents)) if f.kind == DEVIATION]


def test_rounded_whole_euro_value_matches_without_finding(equipment_with_elster_id: None) -> None:
    assert deviations([line(DAYS, "220"), line(KM, "12"), line(EQUIPMENT, "87")], 8640) == []


def test_unrounded_or_wrongly_rounded_equipment_is_a_deviation(
    equipment_with_elster_id: None,
) -> None:
    base = [line(DAYS, "220"), line(KM, "12")]

    (cents,) = deviations([*base, line(EQUIPMENT, "86,40")], 8640)
    (down,) = deviations([*base, line(EQUIPMENT, "86")], 8640)

    assert cents.severity is Severity.WARNING
    assert "nicht gerundet: 86,40 € statt 87 €" in cents.message
    assert "um 1 € abgerundet, zu deinen Ungunsten" in down.message


def test_protocol_12_matches_12_4_km_but_12_4_does_not() -> None:
    assert deviations([line(DAYS, "220"), line(KM, "12")], km=12) == []
    (found,) = deviations([line(DAYS, "220"), line(KM, "12,4")], km=12)
    assert "nicht gerundet: 12,4 km statt 12 km" in found.message


def test_not_yet_computable_value_gets_no_comparison_finding() -> None:
    items = [i for i in entries([line(DAYS, "1")]) if not isinstance(i, FirstWorkplace)]
    found = findings(items)

    assert kinds(found) == [
        UNKNOWN_ELSTER_ID
    ]  # der Fehler "noch nicht berechenbar" ist kein Befund


def test_repeated_days_or_km_are_ambiguous_not_compared() -> None:
    found = findings(entries([line(DAYS, "100", "1_1"), line(DAYS, "120", "2_1"), line(KM, "12")]))

    assert kinds(found) == [AMBIGUOUS, UNKNOWN_ELSTER_ID]
    assert next(f for f in found if f.kind == AMBIGUOUS).severity is Severity.WARNING


def test_lines_without_field_in_the_catalog_are_ignored() -> None:
    found = findings(entries([line(DAYS, "220"), line(KM, "12"), line("E0100004", "Musterstadt")]))

    assert kinds(found) == [UNKNOWN_ELSTER_ID]


def test_latest_taken_in_protocol_counts() -> None:
    old = entries([line(DAYS, "1"), line(KM, "1")], taken=1)
    new = entries([line(DAYS, "220"), line(KM, "12")], taken=2)

    assert kinds(findings(old + new[2:])) == [UNKNOWN_ELSTER_ID]
    assert kinds(findings(new + old[2:])) == [UNKNOWN_ELSTER_ID]


def test_without_protocol_there_is_no_comparison() -> None:
    items: list[Entry] = [i for i in entries([line(DAYS, "1")]) if isinstance(i, FirstWorkplace)]

    assert findings(items) == []


def test_german_numbers() -> None:
    assert parse_german_number("1.234,56") == Decimal("1234.56")
    assert parse_german_number("220") == Decimal(220)
    assert parse_german_number("49,90 €") == Decimal("49.90")
    assert parse_german_number("abc") is None
    assert parse_german_number("1,2,3") is None


# --- Befundliste und Klick zur Stelle im Protokoll ----------------------------------------------


@pytest.fixture
def http(tmp_path: Path) -> httpx.Client:
    site = tmp_path / "ablage"
    site.mkdir()
    shutil.copy(FIXTURE, site / "protokoll.html")
    root = tmp_path / "daten"
    (root / "common").mkdir(parents=True)
    (root / "common" / "sites.json").write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_whole_flow_finding_list_links_to_the_protocol(http: httpx.Client) -> None:
    http.post(
        "/arbeit/erste-taetigkeitsstaette",
        data={"year": "2025", "workdays": "219", "distance_km": "12", "description": "Büro"},
        headers=ORIGIN,
    )
    taken = http.post(
        "/steuerjahr/uebertragungsprotokolle",
        data={"site": "Belege", "path": "protokoll.html", "year": "2025"},
        headers=ORIGIN,
    )
    assert taken.status_code == 303

    page = http.get("/befunde?year=2025")

    assert page.status_code == 200
    assert "Wert 219 Tage, Protokoll 220 Tage" in page.text
    assert "Warnung" in page.text and "E-Kennung unbekannt, nicht abgleichbar" in page.text
    href = next(
        part.split('"')[1]
        for part in page.text.split("href=")[1:]
        if "uebertragungsprotokolle" in part.split('"')[1] and "#" in part.split('"')[1]
    )
    path, _, anchor = href.partition("#")
    target = http.get(path)
    assert target.status_code == 200
    assert f'id="{anchor}"' in target.text
    anlage = http.get("/steuerjahr/anlage-n/2025")
    assert "Wert 219 Tage, Protokoll 220 Tage" in anlage.text
    assert "Befunde" in http.get("/").text
