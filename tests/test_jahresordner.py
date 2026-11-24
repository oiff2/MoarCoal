"""Tests: Jahresordner (Ablageort mit Jahr) und zu welchen Jahren ein Dokument gehört (#182)."""

import datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.documents import belongs_to_year
from moarcoal.storage import Document, Entry, EntryAddress, Put, StoreError, open_store
from moarcoal.storage.entries import entry_kind

PORT = 8799


def write_sites(root: Path, body: dict[str, object]) -> None:
    path = root / "common" / "sites.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


# --- Konfiguration --------------------------------------------------------------------------


def test_sites_with_and_without_year_are_read(tmp_path: Path) -> None:
    write_sites(
        tmp_path,
        {
            "schema": "ablageorte/2",
            "sites": {
                "Steuer": {"path": str(tmp_path / "steuer"), "year": 2025},
                "Scans": {"path": str(tmp_path / "scans")},
            },
        },
    )
    sites = open_store(tmp_path, []).sites
    assert sites.names() == ["Scans", "Steuer"]
    assert sites.year_of("Steuer") == 2025
    assert sites.year_of("Scans") is None
    assert sites.year_folder(2025) == "Steuer"
    assert sites.year_folder(2024) is None


def test_old_form_is_still_read_without_years(tmp_path: Path) -> None:
    write_sites(tmp_path, {"schema": "ablageorte/1", "sites": {"Belege": str(tmp_path)}})
    sites = open_store(tmp_path, []).sites
    assert sites.names() == ["Belege"]
    assert sites.year_of("Belege") is None


def test_two_year_folders_for_one_year_stop_the_start(tmp_path: Path) -> None:
    write_sites(
        tmp_path,
        {
            "schema": "ablageorte/2",
            "sites": {
                "A": {"path": str(tmp_path / "a"), "year": 2025},
                "B": {"path": str(tmp_path / "b"), "year": 2025},
            },
        },
    )
    with pytest.raises(StoreError, match="2025.*A.*B"):
        open_store(tmp_path, [])


@pytest.mark.parametrize("year", [0, "2025", True])
def test_invalid_year_is_rejected(tmp_path: Path, year: object) -> None:
    write_sites(
        tmp_path,
        {"schema": "ablageorte/2", "sites": {"A": {"path": str(tmp_path), "year": year}}},
    )
    with pytest.raises(StoreError):
        open_store(tmp_path, [])


# --- Jahr eines Dokuments -------------------------------------------------------------------


class YearNote(Entry):
    """Ein Eintrag mit Zeitbezug, der auf ein Dokument verweist (nur für den Test)."""

    year: int
    document: EntryAddress


NOTE_KIND = entry_kind(YearNote, "test/1", lambda e: f"users/{e.owner}/notes.json")


def document(
    site: str,
    period_start: datetime.date | None = None,
    period_end: datetime.date | None = None,
) -> Document:
    return Document(
        owner="anna",
        site=site,
        path="a.pdf",
        sha256="0" * 64,
        document_kind=None,
        period_start=period_start,
        period_end=period_end,
    )


@pytest.fixture
def sites_root(tmp_path: Path) -> Path:
    write_sites(
        tmp_path,
        {
            "schema": "ablageorte/2",
            "sites": {
                "Steuer": {"path": str(tmp_path / "steuer"), "year": 2025},
                "Scans": {"path": str(tmp_path / "scans")},
            },
        },
    )
    return tmp_path


def test_period_touching_the_year_decides(sites_root: Path) -> None:
    store = open_store(sites_root, [])
    doc = document(
        "Scans",
        period_start=datetime.date(2024, 7, 1),
        period_end=datetime.date(2025, 6, 30),
    )
    state = store.state()
    assert belongs_to_year(doc, 2024, state, store.sites)
    assert belongs_to_year(doc, 2025, state, store.sites)
    assert not belongs_to_year(doc, 2023, state, store.sites)


def test_without_period_the_year_folder_decides(sites_root: Path) -> None:
    store = open_store(sites_root, [])
    doc = document("Steuer")
    assert belongs_to_year(doc, 2025, store.state(), store.sites)
    assert not belongs_to_year(doc, 2024, store.state(), store.sites)


def test_at_a_site_without_year_every_year_until_referencing_entries_decide(
    sites_root: Path,
) -> None:
    store = open_store(sites_root, [NOTE_KIND])
    doc = document("Scans")
    assert belongs_to_year(doc, 2025, store.state(), store.sites)  # offene Aufgabe: jedes Jahr
    assert belongs_to_year(doc, 2024, store.state(), store.sites)

    store.apply([Put(doc), Put(YearNote(owner="anna", year=2025, document=doc.address))])

    assert belongs_to_year(doc, 2025, store.state(), store.sites)
    assert not belongs_to_year(doc, 2024, store.state(), store.sites)


# --- Vorbelegung des Jahrs ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "beleg.txt").write_text("ohne Jahr im Namen")
    write_sites(tmp_path / "daten", {"schema": "ablageorte/1", "sites": {"Belege": str(site)}})
    app = make_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_intake_form_prefills_the_year_from_the_header(client: httpx.Client) -> None:
    sha = hashlib.sha256(b"ohne Jahr im Namen").hexdigest()
    client.cookies.set("jahr", "2023")
    html = client.get(f"/belege?datei={sha}").text.split('<div class="formular">')[1]
    assert 'name="year" value="2023"' in html
