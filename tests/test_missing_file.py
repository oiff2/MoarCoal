"""Tests: Befund „Datei fehlt“ und Wiederfinden einer verschobenen Datei über den SHA-256 (#191)."""

import shutil
from pathlib import Path

import pytest

from moarcoal.block_findings import block_findings
from moarcoal.documents import TakenIn, take_in
from moarcoal.incoming import (
    MISSING_FILE,
    all_site_files,
    missing_file_findings,
    relocate_documents,
)
from moarcoal.storage import Document, Store, open_store
from moarcoal.values.findings import Severity


@pytest.fixture
def store(tmp_path: Path) -> Store:
    for name in ("ablage", "andere"):
        (tmp_path / name / "2025").mkdir(parents=True)
    (tmp_path / "ablage" / "2025" / "brief.txt").write_text("ein Brief")
    return open_store(
        tmp_path / "daten",
        [],
        sites={"Belege": tmp_path / "ablage", "Andere": tmp_path / "andere"},
    )


def take(store: Store) -> Document:
    result = take_in(store, {}, "anna", "Belege", "2025/brief.txt", "", 2025)
    assert isinstance(result, TakenIn)
    return result.document


def findings(store: Store) -> list[str]:
    return [f.message for f in missing_file_findings(all_site_files(store), store.state(), "anna")]


def test_present_file_gives_no_finding(store: Store) -> None:
    take(store)
    assert findings(store) == []


def test_vanished_file_gives_an_error_on_the_document(store: Store, tmp_path: Path) -> None:
    document = take(store)
    (tmp_path / "ablage" / "2025" / "brief.txt").unlink()
    (finding,) = missing_file_findings(all_site_files(store), store.state(), "anna")
    assert finding.kind == MISSING_FILE
    assert finding.severity is Severity.ERROR
    assert finding.target == document.address
    assert finding.message == "Datei fehlt: Belege/2025/brief.txt"


def test_file_of_another_user_is_not_reported(store: Store, tmp_path: Path) -> None:
    take(store)
    (tmp_path / "ablage" / "2025" / "brief.txt").unlink()
    assert missing_file_findings(all_site_files(store), store.state(), "berta") == []


def test_moved_within_the_site_is_found_again_and_followed(store: Store, tmp_path: Path) -> None:
    document = take(store)
    (tmp_path / "ablage" / "neu").mkdir()
    shutil.move(tmp_path / "ablage" / "2025" / "brief.txt", tmp_path / "ablage" / "neu" / "b.txt")
    assert findings(store) == []  # bis zum Nachführen kein Befund

    lines = relocate_documents(store)

    (moved,) = store.state().of_kind(Document)
    assert moved.address == document.address
    assert moved.path == "neu/b.txt"
    assert lines == ["Belege: 2025/brief.txt -> neu/b.txt"]
    assert relocate_documents(store) == []


def test_moved_to_another_site_is_missing(store: Store, tmp_path: Path) -> None:
    take(store)
    shutil.move(tmp_path / "ablage" / "2025" / "brief.txt", tmp_path / "andere" / "brief.txt")
    assert findings(store) == ["Datei fehlt: Belege/2025/brief.txt"]
    assert relocate_documents(store) == []
    assert next(iter(store.state().of_kind(Document))).path == "2025/brief.txt"


def test_block_findings_carry_it(store: Store, tmp_path: Path) -> None:
    take(store)
    (tmp_path / "ablage" / "2025" / "brief.txt").unlink()
    result = block_findings(
        store.state(), "anna", 2025, {}, lambda: all_site_files(store), store.sites
    )
    assert [f.kind for f in result.late] == [MISSING_FILE]
