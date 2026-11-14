"""Belege-Seite, Reiter Erwartet: Verlinkung mit dem erfüllenden Dokument (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules import MODULES
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
    app = create_app(PORT, tmp_path / "daten", MODULES, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def expect(client: httpx.Client, start: int = 2025) -> ExpectedDocument:
    entry = ExpectedDocument(
        owner="anna", document_kind=KIND, start_year=start, end_year=start, description="Beispiel"
    )
    store_of(client).apply([Put(entry)])
    return entry


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


def test_fulfilled_year_links_to_the_document(client: httpx.Client) -> None:
    expect(client)
    client.post(
        "/belege/aufnehmen", data={"sha256": SHA, "kind": KIND, "year": "2025"}, headers=ORIGIN
    )
    (document,) = store_of(client).state().of_kind(Document)

    page = client.get("/belege/erwartet").text

    assert f'<a href="{document.url}">Belege: Protokoll_2025.html</a>' in page
