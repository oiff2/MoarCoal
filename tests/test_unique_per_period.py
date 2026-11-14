"""Tests: Dokumentart „je Bezugszeitraum nur ein Dokument“ (`unique_per_period`, nur tmp_path)."""

from pathlib import Path

import pytest

from moarcoal.documents import (
    DUPLICATE_DOCUMENT,
    DocumentKind,
    IntakeRejected,
    TakenIn,
    change_document,
    duplicate_findings,
    take_in,
)
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.storage import Applied, Delete, Document, Put, Store, entry_checksum, open_store

ONCE = DocumentKind("once", "Einmalart", True, lambda d, c: [], unique_per_period=True)
FREE = DocumentKind("free", "Freie Art", True, lambda d, c: [])
KINDS = {"once": ONCE, "free": FREE}


@pytest.fixture
def store(tmp_path: Path) -> Store:
    site = tmp_path / "ablage"
    site.mkdir()
    for name in "abcd":
        (site / f"{name}.txt").write_text(name)
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(f'{{"schema": "ablageorte/1", "sites": {{"Belege": "{site}"}}}}')
    return open_store(tmp_path / "daten", [])


def take(
    store: Store, name: str, kind: str = "once", year: int = 2025, user: str = "anna"
) -> TakenIn | IntakeRejected:
    return take_in(store, KINDS, user, "Belege", f"{name}.txt", kind, year)


def documents(store: Store) -> list[Document]:
    return list(store.state().of_kind(Document))


def test_second_document_of_the_same_kind_year_and_user_is_rejected_and_nothing_written(
    store: Store,
) -> None:
    first = take(store, "a")
    assert isinstance(first, TakenIn)

    second = take(store, "b")

    assert isinstance(second, IntakeRejected)
    assert second.reasons == ("Existiert bereits: Einmalart 2025",)
    assert second.existing == first.document
    assert documents(store) == [first.document]


def test_other_year_user_kind_and_documents_without_kind_are_not_affected(store: Store) -> None:
    assert isinstance(take(store, "a"), TakenIn)
    assert isinstance(take(store, "b", year=2024), TakenIn)
    assert isinstance(take(store, "c", user="berta"), TakenIn)
    assert isinstance(take(store, "d", kind="free"), TakenIn)
    assert len(documents(store)) == 4


def test_kind_without_the_property_allows_several_and_beleg_is_free(store: Store) -> None:
    assert isinstance(take(store, "a", kind="free"), TakenIn)
    assert isinstance(take(store, "b", kind="free"), TakenIn)
    assert isinstance(take(store, "c", kind=""), TakenIn)
    assert isinstance(take(store, "d", kind=""), TakenIn)


def test_changing_kind_or_year_into_a_clash_is_rejected(store: Store) -> None:
    first = take(store, "a")
    other_year = take(store, "b", year=2024)
    other_kind = take(store, "c", kind="free")
    assert isinstance(first, TakenIn)
    assert isinstance(other_year, TakenIn)
    assert isinstance(other_kind, TakenIn)

    by_year = change_document(store, KINDS, other_year.document, None, (), "once", 2025)
    by_kind = change_document(store, KINDS, other_kind.document, None, (), "once", 2025)

    for result in (by_year, by_kind):
        assert isinstance(result, IntakeRejected)
        assert result.reasons == ("Existiert bereits: Einmalart 2025",)
        assert result.existing == first.document
    assert store.state().get(other_year.document.address) == other_year.document


def test_a_document_does_not_clash_with_itself(store: Store) -> None:
    first = take(store, "a")
    assert isinstance(first, TakenIn)

    same = change_document(store, KINDS, first.document, None, (), "once", 2025)
    moved = change_document(store, KINDS, first.document, None, (), "once", 2026)

    assert isinstance(same, Applied)
    assert isinstance(moved, Applied)


def test_a_new_document_fits_after_the_existing_one_is_deleted(store: Store) -> None:
    first = take(store, "a")
    assert isinstance(first, TakenIn)
    assert isinstance(take(store, "b"), IntakeRejected)

    deleted = store.apply([Delete(first.document.address, entry_checksum(first.document))])
    assert isinstance(deleted, Applied)

    assert isinstance(take(store, "b"), TakenIn)


def test_existing_duplicates_stay_and_give_a_note_each(store: Store) -> None:
    first = take(store, "a")
    assert isinstance(first, TakenIn)
    later = Document(
        owner="anna",
        site="Belege",
        path="b.txt",
        sha256="1" * 64,
        document_kind="once",
        period_start=first.document.period_start,
        period_end=first.document.period_end,
    )
    # Altbestand: der Schreibweg selbst kennt die Dokumentart nicht
    assert isinstance(store.apply([Put(later)]), Applied)

    found = duplicate_findings(store.state(), "anna", KINDS)

    by_target = {str(f.target): f for f in found}
    assert set(by_target) == {str(first.document.address), str(later.address)}
    assert {f.kind for f in found} == {DUPLICATE_DOCUMENT}
    assert by_target[str(later.address)].href == later.url
    assert len(documents(store)) == 2
    assert duplicate_findings(store.state(), "berta", KINDS) == []


def test_transfer_protocol_and_assessment_are_registered_as_unique() -> None:
    kinds = {k.key: k for k in TAX_YEAR.document_kinds}
    assert len(kinds) == 2
    assert all(k.unique_per_period for k in kinds.values())
