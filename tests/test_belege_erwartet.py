"""Belege-Seite, Reiter Erwartet: Verlinkung mit Ablage und Dokument (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.expected_documents import pending_for
from moarcoal.modules.tax_year import TRANSFER_PROTOCOL
from moarcoal.storage import Document, ExpectedDocument, Put, Store

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
KIND = TRANSFER_PROTOCOL.key


def make_client(tmp_path: Path, filename: str) -> httpx.Client:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / filename).write_bytes(FIXTURE.read_bytes())
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def expect(client: httpx.Client, start: int = 2025) -> ExpectedDocument:
    entry = ExpectedDocument(
        owner="anna", document_kind=KIND, start_year=start, end_year=start, description="Beispiel"
    )
    store_of(client).apply([Put(entry)])
    return entry


def form(client: httpx.Client) -> str:
    return client.get(f"/belege?datei={SHA}").text.split('<div class="formular">')[1]


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    return make_client(tmp_path, "Protokoll_2025.html")


def test_tab_is_part_of_the_belege_page(client: httpx.Client) -> None:
    page = client.get("/belege/erwartet").text
    assert '<a href="/belege/erwartet" aria-current="page">Erwartet</a>' in page
    assert 'href="/belege/dokumente"' in page


def test_old_urls_redirect_keeping_method(client: httpx.Client) -> None:
    for old, new in (
        ("/erwartete-belege", "/belege/erwartet"),
        ("/erwartete-belege/abc", "/belege/erwartet/abc"),
        ("/erwartete-belege/abc/loeschen", "/belege/erwartet/abc/loeschen"),
    ):
        for method in ("GET", "POST"):
            response = client.request(method, old, headers=ORIGIN)
            assert response.status_code == 308
            assert response.headers["location"] == new


def test_open_file_with_matching_kind_and_year_is_offered_to_pending_year(
    client: httpx.Client,
) -> None:
    entry = expect(client)

    assert f'Würde erfüllen: <a href="/belege/erwartet#e-{entry.id}">' in form(client)
    page = client.get("/belege/erwartet").text
    assert f'würde erfüllt durch <a href="/belege?datei={SHA}">Belege: Protokoll_2025.html' in page


def test_no_hint_for_other_year_or_without_expected_document(client: httpx.Client) -> None:
    assert "Würde erfüllen" not in form(client)
    expect(client, start=2024)
    assert "Würde erfüllen" not in form(client)
    assert "würde erfüllt" not in client.get("/belege/erwartet").text


def test_no_hint_without_kind_in_the_name(tmp_path: Path) -> None:
    client = make_client(tmp_path, "unbekannt_2025.html")
    expect(client)
    assert "Würde erfüllen" not in form(client)


def test_fulfilled_year_links_to_the_document_and_gives_no_hint(client: httpx.Client) -> None:
    expect(client)
    client.post(
        "/belege/aufnehmen", data={"sha256": SHA, "kind": KIND, "year": "2025"}, headers=ORIGIN
    )
    (document,) = store_of(client).state().of_kind(Document)

    page = client.get("/belege/erwartet").text

    assert f'<a href="/dokumente/{document.id}">Belege: Protokoll_2025.html</a>' in page
    assert "würde erfüllt" not in page


def test_pending_for_uses_the_fulfilment_rule() -> None:
    entry = ExpectedDocument(owner="anna", document_kind=KIND, start_year=2025)
    assert pending_for([], [entry], KIND, 2025) == [entry]
    assert pending_for([], [entry], KIND, 2024) == []
    assert pending_for([], [entry], "anderes.dokument", 2025) == []
