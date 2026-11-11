"""Tests: Ablageorte, Dokument, Aufnehmen und Einlesen des Übertragungsprotokolls (nur tmp_path)."""

import datetime
import hashlib
import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DocumentKind, IntakeRejected, ReadInError, TakenIn, take_in
from moarcoal.modules.tax_year import (
    REGISTRATION,
    TRANSFER_PROTOCOL,
    ProtocolReading,
)
from moarcoal.modules.tax_year.reading import READER_VERSION, parse_protocol, read_in_protocol
from moarcoal.storage import (
    Applied,
    Document,
    Put,
    SiteFileError,
    StoreError,
    open_store,
)

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
KINDS = {TRANSFER_PROTOCOL.key: TRANSFER_PROTOCOL}


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "2025" / "protokoll.html")
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "daten"


def make_store(root: Path, site: Path):
    return open_store(root, REGISTRATION.kinds, {"Belege": site})


def make_client(root: Path, site: Path) -> httpx.Client:
    root.mkdir(parents=True, exist_ok=True)
    sites = root / "gemeinsam" / "ablageorte.json"
    sites.parent.mkdir(parents=True, exist_ok=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


# --- Einlese-Regel ----------------------------------------------------------------------------


def test_parse_protocol_reads_header_and_fields_as_printed() -> None:
    parsed = parse_protocol(FIXTURE.read_bytes())
    assert (parsed.belegart, parsed.belegversion, parsed.year) == ("E10", "2025", 2025)
    assert str(parsed.received) == "2026-03-01"
    fields = [
        (line.elster_id, line.form, line.form_line, line.label, line.content, line.index)
        for line in parsed.lines
    ]
    assert fields == [
        ("E0203503", "N", "5", "Arbeitstage", "220", "1_1-1-1"),
        ("E0203504", "N", "6", "Einfache Entfernung in km", "12", "1_1-1-1"),
        ("E0107601", "N", "12", "Arbeitsmittel (Art & Anschaffung)", "49,90", "1_1-1-1"),
        ("E0107601", "N", "", "Weiteres Arbeitsmittel", "20,00", "2_1-1-1"),
        ("E0100004", "ESt1A", "", "Ort", "Musterstadt", "1_1-1-1"),
    ]


def test_fundstelle_is_the_full_data_name_and_repeated_elster_id_stay_separate() -> None:
    lines = parse_protocol(FIXTURE.read_bytes()).lines
    assert lines[0].data_name == "id-N-Werbungskosten-Fahrten-E0203503_usb1_1-1-1"
    repeated = [line for line in lines if line.elster_id == "E0107601"]
    assert [line.content for line in repeated] == ["49,90", "20,00"]  # nicht summiert
    assert len({line.data_name for line in repeated}) == 2


def test_parse_protocol_ignores_fields_without_elster_id() -> None:
    parsed = parse_protocol(FIXTURE.read_bytes())
    texts = {line.content for line in parsed.lines}
    assert "wird ignoriert" not in texts
    assert "2025" not in texts  # Vorsatz-Zeitraum hat keine E-Kennung


def test_parse_protocol_empty_year_falls_back_to_belegversion_or_none() -> None:
    html = b"<!-- Belegart: E10 --><!-- Belegversion: 202501 --><!-- Veranlagungsjahr: -->"
    assert parse_protocol(html).year is None
    html = b"<!-- Belegart: E10 --><!-- Veranlagungsjahr: 2024 -->"
    assert parse_protocol(html).year == 2024


def make_document(year: int | None = 2025) -> Document:
    return Document(
        owner="anna",
        site="Belege",
        path="a.html",
        sha256="0" * 64,
        document_kind="transfer_protocol",
        period_start=datetime.date(year, 1, 1) if year else None,
        period_end=datetime.date(year, 12, 31) if year else None,
    )


def test_read_in_stores_fields_from_the_fixture() -> None:
    (reading,) = read_in_protocol(make_document(), FIXTURE.read_bytes())
    assert isinstance(reading, ProtocolReading)
    assert (reading.year, reading.belegversion, len(reading.lines)) == (2025, "2025", 5)
    assert reading.reader_version == READER_VERSION


def test_read_in_refuses_other_documents_and_year_mismatch() -> None:
    with pytest.raises(ReadInError, match="kein Übertragungsprotokoll"):
        read_in_protocol(make_document(), b"<p>nichts</p>")
    with pytest.raises(ReadInError, match="kein Feld mit E-Kennung"):
        read_in_protocol(make_document(), b"<!-- Belegart: E10 --><p>leer</p>")
    with pytest.raises(ReadInError, match="Steuerjahr 2025, eingetragen ist 2024"):
        read_in_protocol(make_document(2024), FIXTURE.read_bytes())
    with pytest.raises(ReadInError, match="Bezugszeitraum"):
        read_in_protocol(make_document(None), FIXTURE.read_bytes())


def test_read_in_accepts_empty_head_year(tmp_path: Path) -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace("Belegversion: 2025", "Belegversion: ")
    (reading,) = read_in_protocol(make_document(2024), html.encode("utf-8"))
    assert isinstance(reading, ProtocolReading) and reading.year == 2024


# --- Ablageorte -------------------------------------------------------------------------------


def test_read_site_file_reads_only_inside_the_site(root: Path, site: Path) -> None:
    store = make_store(root, site)
    assert store.read_site_file("Belege", "2025/protokoll.html") == FIXTURE.read_bytes()
    for bad in ["../x", "/etc/passwd", "", "2025/../../x", "2025/fehlt.html", "2025"]:
        with pytest.raises(SiteFileError):
            store.read_site_file("Belege", bad)
    with pytest.raises(SiteFileError, match="Unbekannter Ablageort"):
        store.read_site_file("Anderswo", "2025/protokoll.html")


def test_read_site_file_rejects_symlink_out_of_the_site(
    root: Path, site: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "geheim.txt"
    outside.write_text("x", encoding="utf-8")
    (site / "link.txt").symlink_to(outside)
    with pytest.raises(SiteFileError, match="hinaus"):
        make_store(root, site).read_site_file("Belege", "link.txt")


def test_sites_come_from_the_shared_file_and_are_not_entries(root: Path, site: Path) -> None:
    file = root / "gemeinsam" / "ablageorte.json"
    file.parent.mkdir(parents=True)
    file.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    store = open_store(root, REGISTRATION.kinds)
    assert store.site_names() == ["Belege"]
    assert store.state().entries == {}


@pytest.mark.parametrize(
    "content",
    [
        '{"schema": "x/1", "sites": {}}',
        "kaputt",
        '{"schema": "ablageorte/1", "sites": {"a": "rel"}}',
    ],
)
def test_invalid_sites_file_stops_the_start(root: Path, content: str) -> None:
    file = root / "gemeinsam" / "ablageorte.json"
    file.parent.mkdir(parents=True)
    file.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError, match="ablageorte.json"):
        open_store(root, REGISTRATION.kinds)


# --- Dokument und Aufnehmen -------------------------------------------------------------------


def test_document_period_must_be_complete() -> None:
    import datetime

    with pytest.raises(ValueError, match="Beginn und Ende"):
        Document(
            owner="a", site="s", path="p", sha256="0" * 64, period_start=datetime.date(2025, 1, 1)
        )


def test_take_in_stores_document_with_hash_and_reading(root: Path, site: Path) -> None:
    store = make_store(root, site)
    result = take_in(
        store, KINDS, "anna", "Belege", "2025/protokoll.html", "transfer_protocol", 2025
    )
    assert isinstance(result, TakenIn)
    assert result.document.sha256 == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    reopened = make_store(root, site).state()
    (document,) = reopened.of_kind(Document)
    (reading,) = reopened.of_kind(ProtocolReading)
    assert (document.site, document.path, document.document_kind) == (
        "Belege",
        "2025/protokoll.html",
        "transfer_protocol",
    )
    assert (str(document.period_start), str(document.period_end)) == ("2025-01-01", "2025-12-31")
    assert reading.document == document.address
    assert reading.reader_version == READER_VERSION
    assert [line.elster_id for line in reading.lines][:2] == ["E0203503", "E0203504"]
    assert (root / "nutzer" / "anna" / "dokumente.json").exists()
    assert (root / "nutzer" / "anna" / "tax_year" / "2025.json").exists()


def test_take_in_does_not_copy_or_change_the_file(root: Path, site: Path) -> None:
    before = (site / "2025" / "protokoll.html").read_bytes()
    take_in(
        make_store(root, site),
        KINDS,
        "anna",
        "Belege",
        "2025/protokoll.html",
        "transfer_protocol",
        2025,
    )
    assert (site / "2025" / "protokoll.html").read_bytes() == before
    assert not list(root.rglob("*.html"))


def test_take_in_rejects_same_file_twice_but_not_for_other_user(root: Path, site: Path) -> None:
    store = make_store(root, site)
    args = ("Belege", "2025/protokoll.html", "transfer_protocol", 2025)
    assert isinstance(take_in(store, KINDS, "anna", *args), TakenIn)
    again = take_in(store, KINDS, "anna", *args)
    assert isinstance(again, IntakeRejected)
    assert "schon aufgenommen" in again.reasons[0]
    assert isinstance(take_in(store, KINDS, "ben", *args), TakenIn)


def test_take_in_rejects_without_writing(root: Path, site: Path) -> None:
    (site / "leer.html").write_text("<p>kein Protokoll</p>", encoding="utf-8")
    store = make_store(root, site)
    for path, year in [("leer.html", 2025), ("fehlt.html", 2025), ("2025/protokoll.html", 1999)]:
        result = take_in(store, KINDS, "anna", "Belege", path, "transfer_protocol", year)
        assert isinstance(result, IntakeRejected)
    assert store.state().entries == {}


def test_take_in_is_one_vorgang(root: Path, site: Path) -> None:
    def failing(document: Document, content: bytes) -> list[ProtocolReading]:
        reading = read_in_protocol(document, content)[0]
        assert isinstance(reading, ProtocolReading)
        return [reading, reading]  # zweimal dieselbe Adresse: der Vorgang wird abgewiesen

    kind = DocumentKind("transfer_protocol", "x", True, failing)
    store = make_store(root, site)
    result = take_in(
        store, {kind.key: kind}, "anna", "Belege", "2025/protokoll.html", kind.key, 2025
    )
    assert isinstance(result, IntakeRejected)
    assert store.state().entries == {}


def test_documents_of_module_state_are_per_user(root: Path, site: Path) -> None:
    from moarcoal.registration import ModuleState

    store = make_store(root, site)
    take_in(store, KINDS, "anna", "Belege", "2025/protokoll.html", "transfer_protocol", 2025)
    assert len(ModuleState(store.state(), REGISTRATION, "anna").documents()) == 1
    assert ModuleState(store.state(), REGISTRATION, "ben").documents() == []
    assert ModuleState(store.state(), REGISTRATION, "anna").documents("andere") == []


def test_document_put_by_hand_is_checked(root: Path, site: Path) -> None:
    store = make_store(root, site)
    bad = Document.model_construct(
        id="ABCDEFGHIJ",
        owner="anna",
        site="s",
        path="p",
        sha256="zz",
        document_kind=None,
        period_start=None,
        period_end=None,
    )
    assert not isinstance(store.apply([Put(bad)]), Applied)


# --- Seiten -----------------------------------------------------------------------------------


def test_pages_take_in_and_show_document_and_lines(root: Path, site: Path) -> None:
    client = make_client(root, site)
    page = client.get("/steuerjahr")
    assert page.status_code == 200
    assert "Noch kein Übertragungsprotokoll" in page.text
    assert '<option value="Belege"' in page.text

    response = client.post(
        "/steuerjahr/uebertragungsprotokolle",
        data={"site": "Belege", "path": "2025/protokoll.html", "year": "2025"},
        headers=ORIGIN,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"]).text
    assert "2025/protokoll.html" in detail
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() in detail
    assert "E0203504" in detail
    assert "49,90" in detail
    assert "Arbeitsmittel (Art &amp; Anschaffung)" in detail
    assert 'id="id-N-Werbungskosten-Fahrten-E0203503_usb1_1-1-1"' in detail
    assert "01.03.2026" in detail
    overview = client.get("/steuerjahr").text
    assert "Belege / 2025/protokoll.html" in overview
    assert response.headers["location"] in overview


def test_page_get_never_writes(root: Path, site: Path) -> None:
    client = make_client(root, site)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    client.get("/steuerjahr")
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def test_page_shows_errors_and_keeps_input(root: Path, site: Path) -> None:
    client = make_client(root, site)
    response = client.post(
        "/steuerjahr/uebertragungsprotokolle",
        data={"site": "Belege", "path": "../x", "year": "2025"},
        headers=ORIGIN,
    )
    assert response.status_code == 422
    assert "ohne" in response.text
    assert 'value="../x"' in response.text
    bad_year = client.post(
        "/steuerjahr/uebertragungsprotokolle",
        data={"site": "Belege", "path": "2025/protokoll.html", "year": "abc"},
        headers=ORIGIN,
    )
    assert bad_year.status_code == 422


def test_detail_of_unknown_or_invalid_reading_is_404(root: Path, site: Path) -> None:
    client = make_client(root, site)
    assert client.get("/steuerjahr/uebertragungsprotokolle/AAAAAAAAAA").status_code == 404
    assert client.get("/steuerjahr/uebertragungsprotokolle/klein").status_code == 404


def test_page_rejects_year_that_contradicts_the_head(root: Path, site: Path) -> None:
    client = make_client(root, site)
    response = client.post(
        "/steuerjahr/uebertragungsprotokolle",
        data={"site": "Belege", "path": "2025/protokoll.html", "year": "2024"},
        headers=ORIGIN,
    )
    assert response.status_code == 422
    assert "gehört zum Steuerjahr 2025, eingetragen ist 2024" in response.text
    assert not (root / "nutzer").exists()


def test_post_needs_origin(root: Path, site: Path) -> None:
    client = make_client(root, site)
    assert client.post("/steuerjahr/uebertragungsprotokolle", data={}).status_code == 403


def test_protocol_line_is_stored_as_elster_id() -> None:
    line = parse_protocol(FIXTURE.read_bytes()).lines[0]
    dumped = line.model_dump(mode="json")
    assert dumped["elster_id"] == line.elster_id
    assert len(dumped) == 7
