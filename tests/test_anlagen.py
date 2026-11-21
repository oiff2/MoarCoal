"""Tests: das Steuerjahr führt mehrere Anlagen je Jahr, mit Übersicht, Seiten und den drei
Gegenproben für jede (nur tmp_path, erfundene Werte)."""

import datetime
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading, registration
from moarcoal.modules.tax_year.anlage_n import ANLAGE_N
from moarcoal.modules.tax_year.anlagen import Anlage, year_anlagen
from moarcoal.modules.tax_year.fields import FormField, Rounding
from moarcoal.modules.tax_year.protocol_check import DEVIATION
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.tax_year.snapshot_check import snapshot_on_filing
from moarcoal.modules.tax_year.structure import FormStructure, StructureField
from moarcoal.storage import Document, Entry, Put, Snapshot
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, Unit, ValueKey
from moarcoal.values.testing import evaluate

PORT = 4711
FORMS = ("ESt1A", "VOR", "SA", "N", "KAP", "V")
NAMES = (
    "Hauptvordruck ESt 1 A",
    "Anlage Vorsorgeaufwand",
    "Anlage Sonderausgaben",
    "Anlage N",
    "Anlage KAP",
    "Anlage V",
)


def line(form: str, elster_id: str, content: str, label: str = "Beispiel") -> ProtocolLine:
    return ProtocolLine(
        elster_id=elster_id,
        form=form,
        form_line="7",
        label=label,
        content=content,
        index="1_1-1-1",
        data_name=f"id-{form}-Angaben-Beispiel-{elster_id}_usb1_1-1-1",
    )


def six_forms() -> tuple[ProtocolLine, ...]:
    """Je Anlage eine Zeile; N nur mit einer E-Kennung, die die Struktur von N kennt."""
    return tuple(
        line(form, f"E09{i:05d}", f"{i},00", f"Feld {form}") for i, form in enumerate(FORMS, 1)
    )


def protocol(lines: tuple[ProtocolLine, ...], year: int = 2025) -> list[Entry]:
    document = Document(
        owner="anna",
        site="Belege",
        path="p.html",
        sha256=f"{1:064x}",
        document_kind="transfer_protocol",
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
        taken_in_at=datetime.datetime(year + 1, 3, 1, tzinfo=datetime.UTC),
    )
    reading = ProtocolReading(
        owner="anna", document=document.address, year=year, reader_version=2, lines=lines
    )
    return [document, reading]


def client(tmp_path: Path, anlagen: tuple[Anlage, ...] = ANLAGEN) -> httpx.Client:
    modules = [registration(anlagen) if m.key == "tax_year" else m for m in MODULES]
    app = make_app(PORT, tmp_path, modules, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def put(http: httpx.Client, entries: list[Entry]) -> None:
    store = http.app.state.store  # type: ignore[attr-defined]
    assert store.apply([Put(e) for e in entries])


# --- Übersicht ------------------------------------------------------------------------------


def test_overview_lists_the_six_forms_of_the_protocol_in_mein_elster_order(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))

    page = http.get("/steuerjahr").text

    positions = [page.index(f">{name}</a>") for name in NAMES]
    assert positions == sorted(positions)
    for slug in ("est1a", "vor", "sa", "n", "kap", "v"):
        assert f'href="/steuerjahr/anlage-{slug}/2025"' in page
        assert http.get(f"/steuerjahr/anlage-{slug}/2025").status_code == 200


def test_without_a_protocol_only_the_form_with_a_catalog_is_listed(tmp_path: Path) -> None:
    page = client(tmp_path).get("/steuerjahr").text

    assert ">Anlage N</a>" in page
    assert ">Anlage KAP</a>" not in page
    assert client(tmp_path).get("/steuerjahr/anlage-kap/2025").status_code == 404


def test_overview_follows_the_year_of_the_header(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))
    http.cookies.set("jahr", "2024")

    page = http.get("/steuerjahr").text

    assert "Für 2024 kennt MoarCoal noch keine Anlagen" in page


def test_form_without_a_stored_structure_gets_one_from_the_protocol(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))

    page = http.get("/steuerjahr/anlage-kap/2025").text

    assert "aus dem Übertragungsprotokoll 2025 abgeleitet" in page
    assert "Feld KAP" in page and "Nr. 7<small>E0900005</small>" in page
    assert "Laut Protokoll" in page and "5,00" in page
    assert "wird noch nicht berechnet" in page
    assert 'href="/steuerjahr/anlage-kap/2025/angaben"' in page


def test_provisional_structure_takes_the_page_from_the_protocol_path() -> None:
    lines = (
        line("KAP", "E0900001", "1", "Eins"),
        line("KAP", "E0900001", "2", "Eins"),  # Wiederholzeile bleibt ein Feld
        line("V", "E0900002", "3", "Fremd"),
    )
    reading = protocol(lines)[1]
    assert isinstance(reading, ProtocolReading)

    (kap,) = [a for a in year_anlagen((), 2025, reading) if a.form == "KAP"]

    assert kap.provisional
    assert [f.e_kennung for f in kap.structure.fields] == ["E0900001"]
    assert kap.structure.fields[0].page == "Angaben"
    assert kap.structure.fields[0].headings == ()  # die übrigen Pfadteile sind interne Kürzel
    assert [f.computed for f in kap.fields] == [False]


def test_n_keeps_its_addresses_and_its_stored_structure(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))

    first = http.get("/steuerjahr/anlage-n/2025").text

    assert "aus dem Übertragungsprotokoll 2025 abgeleitet" not in first  # gespeicherte Struktur
    assert "Bruttoarbeitslohn" in first


# --- eine zweite Anlage anmelden, ohne Code der Seiten zu ändern ----------------------------

KEY = ValueKey("tax_year.kap_demo")
FIELD = FormField(
    KEY, "E0900005", "7", "Beispiel", Unit.EUR, Rounding.EURO_CENTS, computed=True, form="KAP"
)
STRUCTURE = FormStructure(
    "KAP",
    2025,
    False,
    (StructureField("E0900005", "10 - Erträge", ("Abschnitt",), "7", "Beispiel"),),
)


def define_values(forms: object) -> tuple[ValueDefinition, ...]:
    return (
        ValueDefinition(
            CatalogEntry(KEY, "Anlage KAP, Beispiel", Unit.EUR, TimeKind.PERIOD),
            lambda calculation: Amount.eur_cents(1000),
        ),
    )


KAP = Anlage("KAP", {2025: (FIELD,)}, {2025: STRUCTURE}, define_values)


def test_second_form_with_catalog_and_structure_gets_overview_and_pages(tmp_path: Path) -> None:
    http = client(tmp_path, (ANLAGE_N, KAP))

    assert ">Anlage KAP</a>" in http.get("/steuerjahr").text
    page = http.get("/steuerjahr/anlage-kap/2025").text
    assert "Anlage KAP 2025" in page and "10 - Erträge" in page
    assert "Beispiel" in page and "10,00" in page
    assert "Laut Protokoll" not in page
    assert http.get("/steuerjahr/anlage-kap/2025/10").status_code == 200
    assert http.get("/steuerjahr/anlage-kap/2025/gibt-es-nicht").status_code == 404


def test_protocol_check_runs_over_every_form() -> None:
    module = registration((KAP,))
    items = protocol((line("KAP", "E0900005", "5,00"),))

    found = evaluate([module], items).finding_list("anna", 2025).visible

    deviation = [f for f in found if f.kind == DEVIATION]
    assert len(deviation) == 1
    assert "Anlage KAP Nr. 7, Beispiel" in deviation[0].message
    assert deviation[0].href.endswith("#id-KAP-Angaben-Beispiel-E0900005_usb1_1-1-1")


def test_filing_freezes_the_computed_fields_of_every_form() -> None:
    module = registration((KAP,))
    document, reading = protocol((line("KAP", "E0900005", "10,00"),))
    assert isinstance(document, Document)

    (change,) = snapshot_on_filing(
        document, [reading], evaluate([module], [document, reading]), (KAP,)
    )

    assert isinstance(change, Put) and isinstance(change.entry, Snapshot)
    assert [v.ref.key for v in change.entry.values] == [KEY]


# --- Baum der Anlagen -----------------------------------------------------------------------


def test_every_page_of_the_tax_year_shows_the_anlagen_with_their_pages(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))

    page = http.get("/steuerjahr/anlage-kap/2025").text

    assert 'class="anlagen-baum"' in page
    for slug in ("est1a", "vor", "sa", "n", "kap", "v"):
        assert f'href="/steuerjahr/anlage-{slug}/2025"' in page
    assert "<details open>" in page  # die gewählte Anlage ist aufgeklappt
    assert 'href="/steuerjahr/anlage-n/2025/1"' in page  # Seiten anderer Anlagen auch


def test_provisional_pages_carry_the_title_from_mein_elster() -> None:
    lines = (
        ProtocolLine(
            elster_id="E2000401",
            form="VOR",
            form_line="4",
            label="Beispiel",
            content="1,00",
            index="1_1-1-1",
            data_name="id-VOR-AVor-E2000401_usb1_1-1-1",
        ),
    )
    reading = protocol(lines)[1]
    assert isinstance(reading, ProtocolReading)

    (vor,) = [a for a in year_anlagen((), 2025, reading) if a.form == "VOR"]

    assert [p.title for p in vor.pages] == ["1 - Beiträge zur Altersvorsorge"]
    assert [p.slug for p in vor.pages] == ["1"]


def test_anlage_v_has_the_stored_structure_and_shows_the_protocol(tmp_path: Path) -> None:
    http = client(tmp_path)
    put(http, protocol(six_forms()))

    page = http.get("/steuerjahr/anlage-v/2025").text

    assert "1 - Allgemeine Angaben" in page
    assert "aus dem Übertragungsprotokoll 2025 abgeleitet" not in page
    assert "Laut Protokoll" in page and "wird noch nicht berechnet" in page


def test_protocol_column_shows_the_unit_the_protocol_leaves_out(tmp_path: Path) -> None:
    http = client(tmp_path)
    vor = ProtocolLine(
        elster_id="E2000401",
        form="VOR",
        form_line="4",
        label="Beispiel",
        content="1.234",
        index="1_1-1-1",
        data_name="id-VOR-AVor-E2000401_usb1_1-1-1",
    )
    put(http, protocol((vor,)))

    page = http.get("/steuerjahr/anlage-vor/2025").text

    assert '<span class="seite">Laut Protokoll</span> 1.234 €' in page
