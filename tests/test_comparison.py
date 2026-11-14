"""Tests: Abgleich mit dem Übertragungsprotokoll und Befundliste (erfundene Werte, tmp_path).

Die Werte von Arbeit sind fest vorgegeben (`foreign`); nur die Tests am Ende laufen mit dem
echten Modul Arbeit.
"""

import datetime
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DUPLICATE_DOCUMENT
from moarcoal.issuers import DOCUMENT_WITHOUT_ISSUER
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading, registration
from moarcoal.modules.tax_year.anlage_n import (
    FORMS,
    N_EQUIPMENT,
    WORK_DISTANCE_KM,
    WORK_EQUIPMENT,
    WORK_WORKDAYS,
)
from moarcoal.modules.tax_year.comparison import (
    AMBIGUOUS,
    DEVIATION,
    MISSING,
    UNKNOWN_ELSTER_ID,
)
from moarcoal.modules.tax_year.reading import parse_protocol
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import Document, Entry, EntryAddress
from moarcoal.values.engine import Foreign
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import Amount, Period, Subject, Unit
from moarcoal.values.testing import evaluate, fixed, not_yet

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)
DAYS, KM = "E0203503", "E0203504"
EQUIPMENT = "E0204403"
PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))


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


def protocol(lines: list[ProtocolLine], taken: int = 1) -> list[Entry]:
    """Ein aufgenommenes Übertragungsprotokoll 2025: Dokument und eingelesene Zeilen."""
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
    return [document, reading]


def work(workdays: int = 220, km: int = 12, cents: int = 0) -> Foreign:
    """Werte von Arbeit 2025, eine erste Tätigkeitsstätte; ohne `cents` 0 € Arbeitsmittel."""
    return {
        (WORK_WORKDAYS, PLACE, YEAR): fixed(Amount.of(workdays, Unit.DAYS)),
        (WORK_DISTANCE_KM, PLACE, YEAR): fixed(Amount.of(km, Unit.KM)),
        (WORK_EQUIPMENT, None, YEAR): fixed(Amount.eur_cents(cents)),
    }


def findings(
    items: list[Entry], foreign: Foreign | None = None, tax_year: ModuleRegistration = TAX_YEAR
) -> list[Finding]:
    values = evaluate([tax_year], items, work() if foreign is None else foreign)
    return without_issuer_notes(values.finding_list("anna", 2025).visible)


def without_issuer_notes(found: list[Finding]) -> list[Finding]:
    """Die Testdokumente haben keinen Aussteller und teils dieselbe Art im selben Jahr; diese
    Hinweise gehören nicht zum Abgleich."""
    return [f for f in found if f.kind not in (DOCUMENT_WITHOUT_ISSUER, DUPLICATE_DOCUMENT)]


def kinds(found: list[Finding]) -> list[str]:
    return sorted(f.kind for f in without_issuer_notes(found))


def test_matching_protocol_gives_no_finding() -> None:
    assert findings(protocol([line(DAYS, "220"), line(KM, "12")])) == []


def test_field_without_elster_id_gets_a_note() -> None:
    fields = tuple(replace(f, elster_id=None) if f.key == N_EQUIPMENT else f for f in FORMS[2025])

    found = findings(
        protocol([line(DAYS, "220"), line(KM, "12")]), tax_year=registration({2025: fields})
    )

    assert kinds(found) == [UNKNOWN_ELSTER_ID]
    assert found[0].severity is Severity.NOTE


def test_deviation_is_a_warning_with_link_to_the_line() -> None:
    items = protocol([line(DAYS, "219"), line(KM, "12")])
    found = [f for f in findings(items) if f.kind == DEVIATION]

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "220 Tage" in found[0].message and "219 Tage" in found[0].message
    reading = next(i for i in items if isinstance(i, ProtocolReading))
    assert found[0].href == (
        f"/steuerjahr/uebertragungsprotokolle/{reading.id}#id-N-Beispiel-{DAYS}_usb1_1-1-1"
    )


def test_missing_line_is_a_warning() -> None:
    found = [f for f in findings(protocol([line(DAYS, "220")])) if f.kind == MISSING]

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert KM in found[0].message


def deviations(lines: list[ProtocolLine], cents: int = 0, km: int = 12) -> list[Finding]:
    return [f for f in findings(protocol(lines), work(km=km, cents=cents)) if f.kind == DEVIATION]


def test_rounded_whole_euro_value_matches_without_finding() -> None:
    assert deviations([line(DAYS, "220"), line(KM, "12"), line(EQUIPMENT, "87")], 8640) == []


def test_zero_value_matches_a_field_missing_from_the_protocol() -> None:
    assert (
        findings(protocol([line(DAYS, "220"), line(KM, "12")])) == []
    )  # ELSTER überträgt leere Felder nicht


def test_unrounded_or_wrongly_rounded_equipment_is_a_deviation() -> None:
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
    foreign = {**work(), (WORK_WORKDAYS, PLACE, YEAR): not_yet("keine Eingabe")}

    found = findings(protocol([line(DAYS, "1"), line(KM, "12")]), foreign)

    assert found == []  # der Fehler "noch nicht berechenbar" ist kein Befund


def test_repeated_days_or_km_are_ambiguous_not_compared() -> None:
    found = findings(protocol([line(DAYS, "100", "1_1"), line(DAYS, "120", "2_1"), line(KM, "12")]))

    assert kinds(found) == [AMBIGUOUS]
    assert next(f for f in found if f.kind == AMBIGUOUS).severity is Severity.WARNING


def test_lines_without_field_in_the_catalog_are_ignored() -> None:
    found = findings(protocol([line(DAYS, "220"), line(KM, "12"), line("E0100004", "Musterstadt")]))

    assert found == []


def test_latest_taken_in_protocol_counts() -> None:
    old = protocol([line(DAYS, "1"), line(KM, "1")], taken=1)
    new = protocol([line(DAYS, "220"), line(KM, "12")], taken=2)

    assert findings(old + new) == []
    assert findings(new + old) == []


def test_equal_taken_in_moment_is_decided_by_reading_id_not_by_storage_order() -> None:
    def same_moment(items: list[Entry], reading_id: str) -> list[Entry]:
        moment = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
        return [
            i.model_copy(update={"taken_in_at": moment})
            if isinstance(i, Document)
            else i.model_copy(update={"id": reading_id})
            for i in items
        ]

    low = same_moment(protocol([line(DAYS, "1"), line(KM, "1")], taken=1), "AAAAAAAAAA")
    high = same_moment(protocol([line(DAYS, "220"), line(KM, "12")], taken=2), "BBBBBBBBBB")

    assert findings(low + high) == []
    assert findings(high + low) == []


def test_without_protocol_there_is_no_comparison() -> None:
    assert findings([], work(workdays=1)) == []


# --- Mit dem echten Modul Arbeit ----------------------------------------------------------------


def test_no_equipment_after_previous_year_matches_a_missing_field_and_keeps_the_note() -> None:
    from moarcoal.modules.work import REGISTRATION as WORK
    from moarcoal.modules.work import FirstWorkplace, UserInput, WorkEquipment
    from moarcoal.modules.work.values import EQUIPMENT_GAP

    place = FirstWorkplace(owner="anna", year=2025, workdays=220, distance_km=12, description="x")
    bought_2024 = WorkEquipment(
        owner="anna",
        year=2024,
        input=UserInput(amount_cents=4990, date=datetime.date(2024, 3, 14), description="Lampe"),
    )
    items = [place, bought_2024, *protocol([line(DAYS, "220"), line(KM, "12")])]

    found = evaluate([WORK, TAX_YEAR], items).finding_list("anna", 2025).visible

    assert kinds(found) == [EQUIPMENT_GAP]  # Hinweis von Arbeit, kein Befund des Abgleichs


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
        "/belege/aufnehmen",
        data={
            "sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "kind": "transfer_protocol",
            "year": "2025",
        },
        headers=ORIGIN,
    )
    assert taken.status_code == 303

    page = http.get("/befunde?year=2025")

    assert page.status_code == 200
    assert "Wert 219 Tage, Protokoll 220 Tage" in page.text
    assert "Warnung" in page.text
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


# --- Fingerabdruck: gleicher Stand gleich, geänderter Stand anders -------------------------------


def only(found: list[Finding], kind: str) -> Finding:
    (finding,) = [f for f in found if f.kind == kind]
    return finding


def test_deviation_fingerprint_follows_the_value_and_the_protocol_content() -> None:
    base = only(findings(protocol([line(DAYS, "219"), line(KM, "12")])), DEVIATION)

    same = only(findings(protocol([line(DAYS, "219"), line(KM, "12")], taken=2)), DEVIATION)
    other_content = only(findings(protocol([line(DAYS, "218"), line(KM, "12")])), DEVIATION)
    other_value = only(
        findings(protocol([line(DAYS, "219"), line(KM, "12")]), work(workdays=221)), DEVIATION
    )

    assert same.fingerprint == base.fingerprint
    assert other_content.fingerprint != base.fingerprint
    assert other_value.fingerprint != base.fingerprint


def test_missing_fingerprint_follows_the_value() -> None:
    base = only(findings(protocol([line(DAYS, "220")])), MISSING)

    same = only(findings(protocol([line(DAYS, "220")]), work()), MISSING)
    other = only(findings(protocol([line(DAYS, "220")]), work(km=13)), MISSING)

    assert same.fingerprint == base.fingerprint
    assert other.fingerprint != base.fingerprint


def test_ambiguous_fingerprint_follows_the_protocol_lines() -> None:
    def ambiguous(second: str) -> Finding:
        lines = [line(DAYS, "100", "1_1"), line(DAYS, second, "2_1"), line(KM, "12")]
        return only(findings(protocol(lines)), AMBIGUOUS)

    assert ambiguous("120").fingerprint == ambiguous("120").fingerprint
    assert ambiguous("121").fingerprint != ambiguous("120").fingerprint


def test_unknown_elster_id_fingerprint_follows_the_field() -> None:
    def unknown(label: str) -> Finding:
        fields = tuple(
            replace(f, elster_id=None, label=label) if f.key == N_EQUIPMENT else f
            for f in FORMS[2025]
        )
        found = findings(
            protocol([line(DAYS, "220"), line(KM, "12")]), tax_year=registration({2025: fields})
        )
        return only(found, UNKNOWN_ELSTER_ID)

    assert unknown("Arbeitsmittel").fingerprint == unknown("Arbeitsmittel").fingerprint


def test_fixture_protocol_matches_the_catalog_for_all_three_computed_fields() -> None:
    lines = list(parse_protocol(FIXTURE.read_bytes()).lines)

    found = findings(protocol(lines), work(cents=6990))

    # Tage und km stimmen; Arbeitsmittel (69,90 € laut Protokoll) wird gefunden und weicht nur
    # durch die Rundung des Felds ab. Kein Feld „fehlt“.
    assert kinds(found) == [DEVIATION]
    assert EQUIPMENT in found[0].message
