"""Tests: Belege-Seite je Jahr mit drei Abschnitten statt Reitern (#184; nur tmp_path)."""

import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import TRANSFER_PROTOCOL
from moarcoal.storage import Document, ExpectedDocument, Put, Store, entry_checksum
from moarcoal.web.links import document_url, expected_documents_url, site_url

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
KIND = TRANSFER_PROTOCOL.key


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def folders(tmp_path: Path) -> dict[str, Path]:
    """Jahresordner 2025 mit einem Unterordner, Jahresordner 2024 und ein Ablageort ohne Jahr."""
    found = {name: tmp_path / name for name in ("steuer25", "steuer24", "scans")}
    for folder in found.values():
        folder.mkdir()
    (found["steuer25"] / "bank").mkdir()
    (found["steuer25"] / "bank" / "auszug25.txt").write_text("auszug25")
    (found["steuer25"] / "brief25.txt").write_text("brief25")
    (found["steuer24"] / "brief24.txt").write_text("brief24")
    (found["scans"] / "scan.txt").write_text("scan")
    return found


def make_client(
    tmp_path: Path, folders: dict[str, Path], years: dict[str, int] | None = None
) -> httpx.Client:
    years = {"steuer25": 2025, "steuer24": 2024} if years is None else years
    sites = {
        name: {"path": str(folder), **({"year": years[name]} if name in years else {})}
        for name, folder in folders.items()
    }
    config = tmp_path / "daten" / "common" / "sites.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"schema": "ablageorte/2", "sites": sites}), encoding="utf-8")
    app = make_app(PORT, tmp_path / "daten", MODULES, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


@pytest.fixture
def client(tmp_path: Path, folders: dict[str, Path]) -> httpx.Client:
    return make_client(tmp_path, folders)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def main_of(client: httpx.Client, url: str = "/belege") -> str:
    return client.get(url).text.split("<main>")[1]


def section(page: str, name: str) -> str:
    """Der Abschnitt `name` (neu, erwartet, aufgenommen) einer Seite."""
    rest = page.split(f'<details class="abschnitt" id="{name}"', 1)[1]
    return rest.split('<details class="abschnitt"', 1)[0]


FILE_SIZE = re.compile(r"(?<![\w-])\d[\d.,]*\s*(?:KB|MB|GB|Bytes?)\b", re.IGNORECASE)


def shows_file_size(text: str) -> bool:
    """Steht eine Dateigröße (Zahl mit Einheit) im Text? Zufällige Kennungen zählen nicht."""
    return FILE_SIZE.search(text) is not None


def test_file_size_pattern_ignores_ids_but_finds_sizes() -> None:
    assert not shows_file_size('<code>KB12345678</code> <a href="/belege/9KBxyz">AKB</a>')
    for size in ("12 KB", "1,5 MB", "3.2GB", "512 Bytes", "7 kb"):
        assert shows_file_size(f"<td>{size}</td>")


def take(client: httpx.Client, text: str, **fields: str) -> None:
    data = {"sha256": sha(text), "kind": "", "year": "2025", **fields}
    assert client.post("/belege/aufnehmen", data=data, headers=ORIGIN).status_code == 303


def documents(client: httpx.Client) -> list[Document]:
    return sorted(store_of(client).state().of_kind(Document), key=lambda d: d.path)


# --- Aufbau ---------------------------------------------------------------------------------


def test_page_is_titled_with_the_year_of_the_header_and_has_no_tabs(client: httpx.Client) -> None:
    page = main_of(client)
    assert "<h1>Belege 2025</h1>" in page
    assert 'class="reiter"' not in page
    client.cookies.set("jahr", "2024")
    assert "<h1>Belege 2024</h1>" in main_of(client)


def test_three_collapsible_sections_with_counts_in_the_title(client: httpx.Client) -> None:
    store_of(client).apply(
        [Put(ExpectedDocument(owner="anna", document_kind=KIND, start_year=2025, end_year=2025))]
    )
    take(client, "brief25")
    page = main_of(client)
    assert page.index('id="neu"') < page.index('id="erwartet"') < page.index('id="aufgenommen"')
    assert (
        '<summary>Neu im Jahresordner <span class="n">(2)</span></summary>' in page
    )  # auszug25 und scan
    assert '<summary>Erwartete Belege <span class="n">(1)</span></summary>' in page
    assert '<summary>Aufgenommene Belege <span class="n">(1)</span></summary>' in page
    assert page.count('<details class="abschnitt"') == 3


# --- Neu im Jahresordner --------------------------------------------------------------------


def test_new_shows_the_year_folder_with_subfolder_and_the_sites_without_year(
    client: httpx.Client,
) -> None:
    neu = section(main_of(client), "neu")
    assert "steuer25" in neu and "(Jahresordner)" in neu
    assert "auszug25.txt" in neu and "brief25.txt" in neu and "bank" in neu
    assert not shows_file_size(neu)
    assert "brief24.txt" not in neu  # Jahresordner eines anderen Jahrs
    assert "scans" in neu and "scan.txt" in neu
    assert neu.index("brief25.txt") < neu.index("scan.txt")  # erst der Jahresordner


def test_new_offers_taking_in_hiding_and_opening_per_file(client: httpx.Client) -> None:
    neu = section(main_of(client), "neu")
    assert f'href="/belege?datei={sha("brief25")}"' in neu  # Aufnehmen: Formular der Datei
    assert 'action="/belege/ausblenden-direkt"' in neu
    assert f'href="/belege/datei/{sha("brief25")}"' in neu  # öffnen


def test_year_without_year_folder_says_so_and_still_shows_the_sites_without_year(
    client: httpx.Client,
) -> None:
    client.cookies.set("jahr", "2023")
    neu = section(main_of(client), "neu")
    assert "Kein Jahresordner für 2023" in neu
    assert "scan.txt" in neu and "brief25.txt" not in neu and "brief24.txt" not in neu


def test_taken_in_files_leave_new(client: httpx.Client) -> None:
    take(client, "brief25")
    assert "brief25.txt" not in section(main_of(client), "neu")


def test_hidden_files_of_the_shown_sites_are_listed_with_a_count(client: httpx.Client) -> None:
    for name in ("brief25", "brief24"):
        data = {"sha256": sha(name)}
        client.post("/belege/ausblenden", data=data, headers=ORIGIN)
    neu = section(main_of(client), "neu")
    assert "Ausgeblendet (1)" in neu  # brief24 liegt im Jahresordner eines anderen Jahrs
    assert "brief25.txt" in neu.split("Ausgeblendet (1)")[1]
    assert "brief24.txt" not in neu


def test_actions_go_back_to_the_page_and_the_next_open_file_follows(client: httpx.Client) -> None:
    hidden = client.post("/belege/ausblenden-direkt", data={"sha256": sha("scan")}, headers=ORIGIN)
    assert hidden.status_code == 303 and hidden.headers["location"] == site_url()


# --- Erwartete Belege -----------------------------------------------------------------------


def expect(client: httpx.Client, start: int, end: int | None, text: str = "Beispiel") -> None:
    entry = ExpectedDocument(
        owner="anna", document_kind=KIND, start_year=start, end_year=end, description=text
    )
    store_of(client).apply([Put(entry)])


def test_expected_lists_the_due_ones_with_state_and_remove(client: httpx.Client) -> None:
    expect(client, 2025, 2025, "diesmal")
    expect(client, 2023, 2024, "früher")
    erwartet = section(main_of(client), "erwartet")
    assert "diesmal" in erwartet and "früher" not in erwartet
    assert "Übertragungsprotokoll" in erwartet
    assert "ausstehend" in erwartet
    assert "/loeschen" in erwartet and "Entfernen" in erwartet
    assert "+ erwarteten Beleg anlegen" in erwartet


def test_expected_state_is_there_with_a_link_to_the_document(
    client: httpx.Client, folders: dict[str, Path]
) -> None:
    expect(client, 2025, 2025)
    fixture = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
    (folders["steuer25"] / "protokoll.html").write_bytes(fixture.read_bytes())
    data = {"sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "kind": KIND}
    client.post("/belege/aufnehmen", data={**data, "year": "2025"}, headers=ORIGIN)
    (document,) = documents(client)
    erwartet = section(main_of(client), "erwartet")
    assert f'<a href="{document_url(document.id)}">protokoll.html</a>' in erwartet
    assert "ausstehend" not in erwartet


def test_creating_an_expected_document_goes_back_to_the_page(client: httpx.Client) -> None:
    fields = {"document_kind": KIND, "start_year": "2025", "end_year": "", "description": "Neu"}
    response = client.post("/belege/erwartet", data=fields, headers=ORIGIN)
    assert response.status_code == 303 and response.headers["location"] == "/belege#erwartet"
    assert "Neu" in section(main_of(client), "erwartet")


def test_a_refused_expected_document_shows_the_page_with_the_reason(client: httpx.Client) -> None:
    fields = {"document_kind": KIND, "start_year": "abc", "description": "Neu"}
    response = client.post("/belege/erwartet", data=fields, headers=ORIGIN)
    assert response.status_code == 422
    page = response.text.split("<main>")[1]
    assert "<h1>Belege 2025</h1>" in page and "Beginn: Jahr zwischen" in page
    assert 'value="Neu"' in page  # die Eingabe bleibt stehen


def test_removing_an_expected_document_goes_back_to_the_page(client: httpx.Client) -> None:
    expect(client, 2025, 2025)
    (entry,) = store_of(client).state().of_kind(ExpectedDocument)
    response = client.post(
        f"/belege/erwartet/{entry.id}/loeschen",
        data={"checksum": entry_checksum(entry)},
        headers=ORIGIN,
    )
    assert response.status_code == 303 and response.headers["location"] == "/belege#erwartet"
    assert not list(store_of(client).state().of_kind(ExpectedDocument))


# --- Aufgenommene Belege --------------------------------------------------------------------


def test_taken_in_lists_the_documents_of_the_year_with_name_path_kind_and_state(
    client: httpx.Client,
) -> None:
    take(client, "brief25", label="Mitteilung")  # liegt im Jahresordner 2025, ohne Zeitraum
    page = main_of(client)
    aufgenommen = section(page, "aufgenommen")
    assert "Mitteilung" in aufgenommen
    assert "steuer25/brief25.txt" in aufgenommen
    assert '<td class="stand">Beleg' in aufgenommen
    client.cookies.set("jahr", "2024")
    assert "brief25" not in section(main_of(client), "aufgenommen")


def test_a_document_without_period_at_a_site_without_year_belongs_to_no_year(
    client: httpx.Client,
) -> None:
    take(client, "scan")
    assert "scan.txt" not in section(main_of(client), "aufgenommen")
    (document,) = documents(client)
    assert "scan.txt" in main_of(client, document_url(document.id))  # die Seite zeigt es trotzdem


def test_a_document_with_a_period_belongs_to_the_years_it_touches(client: httpx.Client) -> None:
    take(client, "scan", kind="assessment", year="2025")
    assert "scan.txt" in section(main_of(client), "aufgenommen")
    client.cookies.set("jahr", "2024")
    assert "scan.txt" not in section(main_of(client), "aufgenommen")


# --- Adressen -------------------------------------------------------------------------------


def test_addresses_point_to_the_page() -> None:
    assert site_url() == "/belege"
    assert document_url("abc") == "/belege?dokument=abc"
    assert expected_documents_url() == "/belege#erwartet"


def test_old_tab_addresses_redirect_to_the_page(client: httpx.Client) -> None:
    for old, new in (("/belege/dokumente", "/belege"), ("/belege/erwartet", "/belege#erwartet")):
        response = client.get(old)
        assert response.status_code == 308 and response.headers["location"] == new


def test_a_missing_file_finding_links_to_the_document_on_the_page(
    tmp_path: Path, client: httpx.Client, folders: dict[str, Path]
) -> None:
    take(client, "brief25")
    (folders["steuer25"] / "brief25.txt").unlink()
    (document,) = documents(client)
    findings = main_of(client, "/befunde?year=2025")
    assert f'href="{document_url(document.id)}"' in findings
    assert "Datei fehlt" in findings


def test_get_of_the_page_writes_nothing(tmp_path: Path, client: httpx.Client) -> None:
    root = tmp_path / "daten"
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    main_of(client)
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def test_older_urls_redirect_keeping_method(client: httpx.Client) -> None:
    for old, new in (
        ("/erwartete-belege", "/belege/erwartet"),
        ("/erwartete-belege/abc", "/belege/erwartet/abc"),
        ("/erwartete-belege/abc/loeschen", "/belege/erwartet/abc/loeschen"),
    ):
        for method in ("GET", "POST"):
            response = client.request(method, old, headers=ORIGIN)
            assert response.status_code == 308 and response.headers["location"] == new
