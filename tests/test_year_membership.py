"""Jahreszugehörigkeit eines Dokuments in der Befundliste: dieselbe Regel wie auf der Belege-Seite
(`belongs_to_year`, #216; nur tmp_path)."""

import datetime
from pathlib import Path

import pytest

from moarcoal.documents import DocumentKind, TakenIn, kind_title, take_in
from moarcoal.proposals import UNCONFIRMED
from moarcoal.storage import (
    Document,
    Proposal,
    ProposalField,
    Put,
    ReadInDifference,
    Rereading,
    Store,
    open_store,
)
from moarcoal.values.engine import Values
from moarcoal.values.findings import READ_IN_CHANGED

KIND = DocumentKind("art", "Beispielart", True, lambda d, c: [], 1)
NOW = datetime.datetime(2025, 3, 1, 12, 0)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    year_folder = tmp_path / "ablage2024"
    year_folder.mkdir()
    (year_folder / "quittung.pdf").write_bytes(b"erfundener Inhalt")
    return open_store(
        tmp_path / "daten", [], sites={"Jahr24": year_folder}, site_years={"Jahr24": 2024}
    )


def document_in_year_folder(store: Store) -> Document:
    """Ein Dokument ohne Bezugszeitraum im Jahresordner 2024."""
    result = take_in(store, {}, "anna", "Jahr24", "quittung.pdf", "", 2024)
    assert isinstance(result, TakenIn)
    assert result.document.period_start is None
    return result.document


def kinds_in_findings(store: Store, year: int) -> list[str]:
    values = Values([], store.state(), sites=store.sites)
    return [f.kind for f in values.finding_list("anna", year).visible]


def test_open_proposal_counts_only_in_the_year_of_the_year_folder(store: Store) -> None:
    document = document_in_year_folder(store)
    field = ProposalField(value="12,00", location="Seite 1")
    proposal = Proposal(
        owner="anna",
        document=document.address,
        template_version=1,
        fields={"betrag": field},
        raw="{}",
        created_at=NOW,
    )
    store.apply([Put(proposal)])
    assert UNCONFIRMED in kinds_in_findings(store, 2024)
    assert UNCONFIRMED not in kinds_in_findings(store, 2025)


def test_rereading_counts_only_in_the_year_of_the_year_folder(store: Store) -> None:
    document = document_in_year_folder(store)
    difference = ReadInDifference(location="Zeile 3", before="1", after="2")
    rereading = Rereading(
        owner="anna",
        document=document.address,
        reread_at=NOW,
        version_before=1,
        version_after=2,
        differences=(difference,),
        difference_count=1,
    )
    store.apply([Put(rereading)])
    assert READ_IN_CHANGED in kinds_in_findings(store, 2024)
    assert READ_IN_CHANGED not in kinds_in_findings(store, 2025)


def test_kind_title_falls_back_to_the_key_and_is_empty_without_a_kind() -> None:
    kinds = {"art": KIND}
    assert kind_title(kinds, "art") == "Beispielart"
    assert kind_title(kinds, "verschwunden") == "verschwunden"
    assert kind_title(kinds, None) == ""
    assert kind_title(kinds, "") == ""
