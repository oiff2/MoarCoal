"""Tests: die Einordnung des Eingangs (`Incoming`) über ihre Schnittstelle, ohne HTTP (#217)."""

import shutil
from pathlib import Path

import pytest

from moarcoal.documents import TakenIn, take_in
from moarcoal.incoming import (
    Classification,
    Incoming,
    Unavailable,
    all_site_files,
    hide_file,
    hide_folder,
)
from moarcoal.storage import Applied, Document, HiddenFolder, SiteFile, Store, open_store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    for name in ("jahr", "scan"):
        (tmp_path / name / "ordner").mkdir(parents=True)
    (tmp_path / "jahr" / "brief.txt").write_text("ein Brief")
    (tmp_path / "jahr" / "ordner" / "rechnung.txt").write_text("eine Rechnung")
    (tmp_path / "scan" / "kopie.txt").write_text("ein Brief")  # gleicher Inhalt wie brief.txt
    sites = {"jahr": tmp_path / "jahr", "scan": tmp_path / "scan"}
    return open_store(tmp_path / "daten", [], sites=sites)


def incoming(store: Store, user: str = "anna") -> Incoming:
    return Incoming(all_site_files(store), store.state(), user)


def file(store: Store, site: str, path: str) -> SiteFile:
    return next(f for f in all_site_files(store) if (f.site, f.path) == (site, path))


def take(store: Store, site: str, path: str, user: str = "anna") -> Document:
    result = take_in(store, {}, user, site, path, "", 2025)
    assert isinstance(result, TakenIn)
    return result.document


def classes(store: Store, user: str = "anna") -> dict[tuple[str, str], Classification]:
    eingang = incoming(store, user)
    return {(f.site, f.path): eingang.classify(f) for f in eingang.files}


def test_everything_is_open_at_first_and_same_content_counts_once(store: Store) -> None:
    assert set(classes(store).values()) == {Classification.OPEN}
    assert [(f.site, f.path) for f in incoming(store).open_files()] == [
        ("jahr", "brief.txt"),
        ("jahr", "ordner/rechnung.txt"),
    ]  # kopie.txt (scan) hat den Inhalt von brief.txt: einmal, mit dem ersten Pfad


def test_open_can_be_limited_to_sites_in_order_and_the_first_site_wins(store: Store) -> None:
    assert [(f.site, f.path) for f in incoming(store).open_files(["scan", "jahr"])] == [
        ("scan", "kopie.txt"),
        ("jahr", "ordner/rechnung.txt"),
    ]


def test_taken_file_is_taken_and_its_copy_elsewhere_is_a_same_content_hint(store: Store) -> None:
    document = take(store, "jahr", "brief.txt")
    assert classes(store) == {
        ("jahr", "brief.txt"): Classification.TAKEN,
        ("jahr", "ordner/rechnung.txt"): Classification.OPEN,
        ("scan", "kopie.txt"): Classification.SAME_CONTENT,
    }
    eingang = incoming(store)
    assert [(f.path, d) for f, d in eingang.same_content()] == [("kopie.txt", document)]
    assert [f.path for f in eingang.open_files()] == ["ordner/rechnung.txt"]


def test_taken_beats_hidden_the_file_stays_taken_and_gives_no_hint(store: Store) -> None:
    take(store, "jahr", "brief.txt")
    assert isinstance(hide_file(store, file(store, "jahr", "brief.txt"), ""), Applied)
    assert classes(store)[("jahr", "brief.txt")] is Classification.TAKEN
    assert (
        classes(store)[("scan", "kopie.txt")] is Classification.TAKEN
    )  # ausgeblendet: kein Hinweis
    assert incoming(store).same_content() == []


def test_taken_by_another_user_does_not_count_for_this_one(store: Store) -> None:
    take(store, "jahr", "brief.txt", user="berta")
    sha = file(store, "jahr", "brief.txt").sha256
    assert classes(store, "anna")[("jahr", "brief.txt")] is Classification.OPEN
    assert incoming(store, "anna").is_taken(sha) is False
    assert incoming(store, "berta").is_taken(sha) is True


def test_hidden_file_hides_every_copy_of_its_content(store: Store) -> None:
    assert isinstance(hide_file(store, file(store, "scan", "kopie.txt"), "Notiz"), Applied)
    assert classes(store) == {
        ("jahr", "brief.txt"): Classification.HIDDEN,
        ("jahr", "ordner/rechnung.txt"): Classification.OPEN,
        ("scan", "kopie.txt"): Classification.HIDDEN,
    }
    assert [f.path for f in incoming(store).open_files()] == ["ordner/rechnung.txt"]


def test_hidden_folder_hides_what_is_below_it_at_any_depth_and_counts_it(store: Store) -> None:
    assert hide_folder(store, store.state(), "jahr", "ordner") is not None
    assert classes(store)[("jahr", "ordner/rechnung.txt")] is Classification.IN_HIDDEN_FOLDER
    assert classes(store)[("jahr", "brief.txt")] is Classification.OPEN
    (folder,) = store.state().of_kind(HiddenFolder)
    assert incoming(store).count_under(folder) == 1


def test_taken_file_in_a_hidden_folder_stays_taken(store: Store) -> None:
    take(store, "jahr", "ordner/rechnung.txt")
    hide_folder(store, store.state(), "jahr", "ordner")
    assert classes(store)[("jahr", "ordner/rechnung.txt")] is Classification.TAKEN


def test_resolve_gives_the_open_file_or_the_reason(store: Store, tmp_path: Path) -> None:
    brief = file(store, "jahr", "brief.txt")
    take(store, "jahr", "ordner/rechnung.txt")
    rechnung = file(store, "jahr", "ordner/rechnung.txt")
    (tmp_path / "jahr" / "brief.txt").write_text("geändert")
    (tmp_path / "scan" / "kopie.txt").unlink()
    eingang = incoming(store)
    assert eingang.resolve("jahr", "brief.txt", brief.sha256) is Unavailable.CHANGED
    assert eingang.resolve("scan", "kopie.txt", brief.sha256) is Unavailable.MISSING
    assert eingang.resolve("jahr", "ordner/rechnung.txt", rechnung.sha256) is Unavailable.NOT_OPEN
    changed = file(store, "jahr", "brief.txt")
    assert eingang.resolve("jahr", "brief.txt", changed.sha256) == changed


def test_document_file_is_present_moved_or_missing(store: Store, tmp_path: Path) -> None:
    missing = take(store, "jahr", "brief.txt")
    moved = take(store, "jahr", "ordner/rechnung.txt")
    assert incoming(store).missing_documents("anna") == []
    assert incoming(store).moved_documents() == []

    (tmp_path / "jahr" / "ordner" / "rechnung.txt").rename(tmp_path / "jahr" / "neu.txt")
    shutil.move(tmp_path / "jahr" / "brief.txt", tmp_path / "scan" / "brief.txt")  # anderer Ort
    eingang = incoming(store)
    assert eingang.moved_documents() == [(moved, "neu.txt")]
    assert eingang.missing_documents("anna") == [missing]
    assert eingang.missing_documents("berta") == []


def test_moved_file_is_taken_and_gives_no_hint(store: Store, tmp_path: Path) -> None:
    take(store, "jahr", "ordner/rechnung.txt")
    (tmp_path / "jahr" / "ordner" / "rechnung.txt").rename(tmp_path / "jahr" / "neu.txt")
    assert classes(store)[("jahr", "neu.txt")] is Classification.TAKEN
    assert incoming(store).same_content() == []
