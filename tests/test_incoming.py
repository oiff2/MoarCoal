"""Tests: Eingang, Ausblenden im Eingang und der Befund „Dateien im Eingang“ (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DocumentKind
from moarcoal.incoming import all_site_files, hide_file, incoming_files
from moarcoal.modules.tax_year import REGISTRATION
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import Applied, HiddenFile, SiteFileError, open_store

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    (folder / "2025" / "protokoll.html").write_bytes(FIXTURE.read_bytes())
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "daten"


def make_client(root: Path, site: Path, user: str = "anna") -> httpx.Client:
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True, exist_ok=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, root, user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def take(client: httpx.Client, sha: str = SHA, year: str = "2025") -> httpx.Response:
    data = {"sha256": sha, "kind": "transfer_protocol", "year": year}
    return client.post("/eingang/aufnehmen", data=data, headers=ORIGIN)


def main_of(client: httpx.Client, url: str) -> str:
    return client.get(url).text.split("<main>")[1]


# --- Auflisten ---------------------------------------------------------------------------------


def test_list_site_files_is_recursive_with_size_and_sha256(root: Path, site: Path) -> None:
    (site / "lose.txt").write_text("abc", encoding="utf-8")
    store = open_store(root, REGISTRATION.kinds, {"Belege": site})
    files = {f.path: f for f in store.list_site_files("Belege")}
    assert sorted(files) == ["2025/protokoll.html", "lose.txt"]
    assert files["lose.txt"].size == 3
    assert files["lose.txt"].sha256 == hashlib.sha256(b"abc").hexdigest()
    assert files["2025/protokoll.html"].sha256 == SHA
    with pytest.raises(SiteFileError, match="Unbekannter Ablageort"):
        store.list_site_files("Anderswo")


def test_list_site_files_skips_links_out_of_the_site(
    root: Path, site: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "geheim"
    outside.mkdir()
    (outside / "x.txt").write_text("x", encoding="utf-8")
    (site / "datei-link.txt").symlink_to(outside / "x.txt")
    (site / "ordner-link").symlink_to(outside, target_is_directory=True)
    (site / "kaputt").symlink_to(outside / "fehlt.txt")
    store = open_store(root, REGISTRATION.kinds, {"Belege": site})
    assert [f.path for f in store.list_site_files("Belege")] == ["2025/protokoll.html"]


def test_list_site_files_keeps_links_inside_the_site(root: Path, site: Path) -> None:
    (site / "kopie.html").symlink_to(site / "2025" / "protokoll.html")
    store = open_store(root, REGISTRATION.kinds, {"Belege": site})
    assert [f.path for f in store.list_site_files("Belege")] == [
        "2025/protokoll.html",
        "kopie.html",
    ]


def test_same_content_twice_is_one_file_in_the_incoming_list(root: Path, site: Path) -> None:
    (site / "kopie.html").write_bytes(FIXTURE.read_bytes())
    store = open_store(root, REGISTRATION.kinds, {"Belege": site})
    waiting = incoming_files(all_site_files(store), store.state(), "anna")
    assert [f.path for f in waiting] == ["2025/protokoll.html"]


# --- Seite -------------------------------------------------------------------------------------


def test_new_file_is_listed_and_gone_after_taking_in_even_when_renamed(
    root: Path, site: Path
) -> None:
    client = make_client(root, site)
    page = client.get("/eingang").text
    assert "2025/protokoll.html" in page
    assert "Übertragungsprotokoll" in page
    taken = take(client)
    assert taken.status_code == 303
    assert taken.headers["location"].startswith("/steuerjahr/uebertragungsprotokolle/")
    assert "2025/protokoll.html" not in waiting(client)
    (site / "2025" / "protokoll.html").rename(site / "umbenannt.html")
    assert "umbenannt.html" not in client.get("/eingang").text


def test_taking_in_is_per_user_hiding_is_for_all(root: Path, site: Path) -> None:
    anna = make_client(root, site, "anna")
    take(anna)
    ben = make_client(root, site, "ben")
    assert "2025/protokoll.html" in ben.get("/eingang").text  # Ben hat sie nicht aufgenommen
    hidden = anna.post("/eingang/ausblenden", data={"sha256": SHA}, headers=ORIGIN)
    assert hidden.status_code == 409  # für Anna schon aufgenommen, nicht mehr im Eingang
    assert ben.post("/eingang/ausblenden", data={"sha256": SHA}, headers=ORIGIN).status_code == 303
    assert "2025/protokoll.html" not in waiting(make_client(root, site, "carla"))


def test_hiding_stores_a_common_entry_with_optional_note(root: Path, site: Path) -> None:
    client = make_client(root, site)
    response = client.post(
        "/eingang/ausblenden", data={"sha256": SHA, "note": " Muster "}, headers=ORIGIN
    )
    assert response.status_code == 303 and response.headers["location"] == "/eingang"
    stored = json.loads((root / "common" / "hidden_files.json").read_text(encoding="utf-8"))
    assert stored["schema"] == "datenebene/1"
    (entry,) = stored["entries"].values()
    assert entry["owner"] == "common"
    assert (entry["sha256"], entry["site"], entry["path"], entry["note"]) == (
        SHA,
        "Belege",
        "2025/protokoll.html",
        "Muster",
    )
    assert "2025/protokoll.html" not in waiting(client)
    again = client.post("/eingang/ausblenden", data={"sha256": SHA}, headers=ORIGIN)
    assert again.status_code == 409


def waiting(client: httpx.Client) -> str:
    """Der Teil der Seite Eingang oberhalb von „Ausgeblendet“."""
    return client.get("/eingang").text.split("<h2>Ausgeblendet")[0]


def hide(client: httpx.Client, note: str = "") -> None:
    client.post("/eingang/ausblenden", data={"sha256": SHA, "note": note}, headers=ORIGIN)


def checksum_in(client: httpx.Client) -> str:
    return client.get("/eingang").text.split('name="checksum" value="')[1].split('"')[0]


def test_hidden_section_shows_and_showing_brings_the_file_back_for_all(
    root: Path, site: Path
) -> None:
    anna = make_client(root, site, "anna")
    assert "Ausgeblendet" not in anna.get("/eingang").text
    hide(anna, "Muster <b>")
    page = anna.get("/eingang").text
    assert "Ausgeblendet" in page and "Muster &lt;b&gt;" in page and "Muster <b>" not in page
    ben = make_client(root, site, "ben")
    take(ben)  # Ben hat sie aufgenommen
    data = {"sha256": SHA, "checksum": checksum_in(anna)}
    response = anna.post("/eingang/einblenden", data=data, headers=ORIGIN)
    assert response.status_code == 303 and response.headers["location"] == "/eingang"
    assert "Ausgeblendet" not in anna.get("/eingang").text
    assert "2025/protokoll.html" in waiting(anna)
    assert "2025/protokoll.html" in waiting(make_client(root, site, "carla"))
    assert "2025/protokoll.html" not in waiting(ben)


def test_showing_with_stale_checksum_or_missing_entry_gives_a_notice(
    root: Path, site: Path
) -> None:
    client = make_client(root, site)
    hide(client)
    stale = client.post(
        "/eingang/einblenden", data={"sha256": SHA, "checksum": "0" * 64}, headers=ORIGIN
    )
    assert stale.status_code == 409 and "inzwischen geändert" in stale.text
    assert "Ausgeblendet" in client.get("/eingang").text
    data = {"sha256": SHA, "checksum": checksum_in(client)}
    client.post("/eingang/einblenden", data=data, headers=ORIGIN)
    gone = client.post("/eingang/einblenden", data=data, headers=ORIGIN)
    assert gone.status_code == 409 and "nicht mehr" in gone.text


def test_hidden_file_gone_from_the_site_is_listed_and_can_be_shown(root: Path, site: Path) -> None:
    client = make_client(root, site)
    hide(client)
    (site / "2025" / "protokoll.html").unlink()
    assert "Ausgeblendet" in client.get("/eingang").text
    data = {"sha256": SHA, "checksum": checksum_in(client)}
    assert client.post("/eingang/einblenden", data=data, headers=ORIGIN).status_code == 303
    page = client.get("/eingang").text
    assert "Ausgeblendet" not in page and "2025/protokoll.html" not in page


def test_hide_file_without_note_is_fine(root: Path, site: Path) -> None:
    store = open_store(root, REGISTRATION.kinds, {"Belege": site})
    (file,) = store.list_site_files("Belege")
    assert isinstance(hide_file(store, file, ""), Applied)
    (hidden,) = store.state().of_kind(HiddenFile)
    assert hidden.note == ""


def test_rejection_stays_in_the_row_with_422(root: Path, site: Path) -> None:
    client = make_client(root, site)
    response = take(client, year="2024")
    assert response.status_code == 422
    assert "gehört zum Steuerjahr 2025, eingetragen ist 2024" in response.text
    assert "2025/protokoll.html" in response.text
    assert 'value="2024"' in response.text
    assert not (root / "users").exists()
    assert take(client, year="abc").status_code == 422
    no_kind = client.post(
        "/eingang/aufnehmen", data={"sha256": SHA, "kind": "", "year": "2025"}, headers=ORIGIN
    )
    assert no_kind.status_code == 422
    assert take(client, sha="0" * 64).status_code == 409


def test_get_never_writes_and_post_needs_origin(root: Path, site: Path) -> None:
    client = make_client(root, site)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    client.get("/eingang")
    client.get("/befunde?year=2025")
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
    assert client.post("/eingang/aufnehmen", data={"sha256": SHA}).status_code == 403
    assert client.post("/eingang/ausblenden", data={"sha256": SHA}).status_code == 403
    assert client.post("/eingang/einblenden", data={"sha256": SHA}).status_code == 403


def test_navigation_links_to_the_incoming_page(root: Path, site: Path) -> None:
    assert 'href="/eingang"' in make_client(root, site).get("/").text


# --- Befund „Dateien im Eingang“ -----------------------------------------------------------------


def test_finding_counts_files_links_to_the_page_and_vanishes(root: Path, site: Path) -> None:
    client = make_client(root, site)
    page = main_of(client, "/befunde?year=2025")
    assert "1 Datei im Eingang" in page
    assert 'href="/eingang"' in page
    take(client)
    assert "im Eingang" not in main_of(client, "/befunde?year=2025")


def test_finding_is_per_user(root: Path, site: Path) -> None:
    anna = make_client(root, site, "anna")
    take(anna)
    ben = make_client(root, site, "ben")
    assert "1 Datei im Eingang" in main_of(ben, "/befunde?year=2025")
    assert "im Eingang" not in main_of(anna, "/befunde?year=2025")


def test_finding_comes_back_when_the_set_of_files_changes(root: Path, site: Path) -> None:
    client = make_client(root, site)
    page = main_of(client, "/befunde?year=2025")
    fingerprint = page.split('name="fingerprint" value="')[1].split('"')[0]
    dismissed = client.post(
        "/befunde/ausblenden",
        data={
            "year": "2025",
            "kind": "incoming_files",
            "target": "eingang",
            "fingerprint": fingerprint,
            "note": "später",
        },
        headers=ORIGIN,
    )
    assert dismissed.status_code == 303
    assert "1 Datei im Eingang" not in main_of(client, "/befunde?year=2025")
    (site / "neu.txt").write_text("neu", encoding="utf-8")
    again = main_of(client, "/befunde?year=2025")
    assert "2 Dateien im Eingang" in again
    assert "war ausgeblendet: später" in again


def test_year_input_is_hidden_for_kinds_without_period(root: Path, site: Path) -> None:
    contract = DocumentKind("demo.contract", "Beispielvertrag", False, lambda d, b: [])
    demo = ModuleRegistration(
        key="demo",
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        document_kinds=(contract,),
    )
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True, exist_ok=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, root, [REGISTRATION, demo], user="anna")
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    page = main_of(client, "/eingang")
    assert '<option value="demo.contract" data-ohne-zeitraum>' in page
    assert '<option value="transfer_protocol">' in page
    assert '<label class="jahr">' in page
    css = Path("src/moarcoal/static/app.css").read_text(encoding="utf-8")
    assert "form:has(option[data-ohne-zeitraum]:checked) .jahr { display: none; }" in css
