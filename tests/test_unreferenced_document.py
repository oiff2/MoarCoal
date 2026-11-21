"""Tests: Befund „Auf diesen Beleg verweist kein Eintrag“ (#190, nur tmp_path)."""

from pathlib import Path

import pytest

from moarcoal.block_findings import block_findings
from moarcoal.documents import (
    UNREFERENCED_DOCUMENT,
    DocumentKind,
    TakenIn,
    take_in,
    unreferenced_document_findings,
)
from moarcoal.storage import Document, Entry, EntryAddress, Put, Store, entry_kind, open_store
from moarcoal.values.findings import Finding, Severity
from moarcoal.web.helpers import finding_url
from moarcoal.web.links import document_url

READABLE = DocumentKind("lesbar", "Lesbare Art", True, lambda d, c: [], 1)
KINDS = {"lesbar": READABLE}


class YearNote(Entry):
    """Ein Eintrag mit Zeitbezug, der auf ein Dokument verweist (nur für den Test)."""

    year: int
    document: EntryAddress


NOTE_KIND = entry_kind(YearNote, "test/1", lambda e: f"users/{e.owner}/notes.json")


@pytest.fixture
def store(tmp_path: Path) -> Store:
    jahr = tmp_path / "ablage2025"
    jahr.mkdir()
    (jahr / "a.txt").write_text("a")
    (jahr / "b.txt").write_text("b")
    frei = tmp_path / "frei"
    frei.mkdir()
    (frei / "c.txt").write_text("c")
    return open_store(
        tmp_path / "daten",
        [NOTE_KIND],
        sites={"Jahr25": jahr, "Frei": frei},
        site_years={"Jahr25": 2025},
    )


def take(store: Store, name: str, kind: str = "", site: str = "Jahr25") -> Document:
    result = take_in(store, KINDS, "anna", site, name, kind, 2025)
    assert isinstance(result, TakenIn)
    return result.document


def found(store: Store, year: int = 2025, user: str = "anna") -> list[Finding]:
    return unreferenced_document_findings(
        store.state(), user, year, KINDS, store.sites, store.entry_kinds
    )


def test_receipt_without_reference_is_a_note_on_the_document(store: Store) -> None:
    document = take(store, "a.txt")
    (finding,) = found(store)
    assert finding.kind == UNREFERENCED_DOCUMENT
    assert finding.severity is Severity.NOTE
    assert finding.target == document.address
    assert finding.href == ""  # den Link baut die Anbindung
    assert finding_url((), store.state(), finding) == document_url(document.id)


def test_document_with_a_reading_kind_gives_no_finding(store: Store) -> None:
    take(store, "a.txt", "lesbar")
    assert found(store) == []


def test_other_year_other_user_and_site_without_year_are_not_reported(store: Store) -> None:
    take(store, "a.txt")
    take(store, "c.txt", site="Frei")  # kein Jahr, kein Eintrag verweist darauf
    assert found(store, 2024) == []
    assert found(store, user="berta") == []
    assert len(found(store)) == 1


def test_it_goes_away_when_an_entry_refers_to_the_document(store: Store) -> None:
    document = take(store, "a.txt")
    other = take(store, "b.txt")
    assert len(found(store)) == 2
    store.apply([Put(YearNote(owner="anna", year=2025, document=document.address))])
    assert [f.target for f in found(store)] == [other.address]


def test_block_findings_carry_it(store: Store) -> None:
    take(store, "a.txt")
    result = block_findings(
        store.state(), "anna", 2025, KINDS, None, store.sites, store.entry_kinds
    )
    assert [f.kind for f in result.late] == [UNREFERENCED_DOCUMENT]
