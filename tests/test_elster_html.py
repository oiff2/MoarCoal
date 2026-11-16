"""Tests: gemeinsamer Kopf der HTML-Dokumente aus Mein ELSTER (Bezugszeitraum, Belegart, Jahr)."""

import datetime

import pytest

from moarcoal.documents import ReadInError
from moarcoal.modules.elster_html import parse_elster_document
from moarcoal.storage import Document

HEAD = b"<!-- Belegart: XY1 --><!-- Veranlagungsjahr: 2025 -->"
ROW = b'<table><tr><td>1</td><td>Feld</td><td><span data-name="id-XY1-A">7</span></td></tr></table>'


def make_document(year: int | None = 2025) -> Document:
    return Document(
        owner="anna",
        site="Belege",
        path="beleg.html",
        sha256="0" * 64,
        document_kind="beispiel",
        period_start=datetime.date(year, 1, 1) if year else None,
        period_end=datetime.date(year, 12, 31) if year else None,
    )


def test_gives_the_year_of_the_document_and_the_parsed_file() -> None:
    year, parsed = parse_elster_document(make_document(), HEAD + ROW, "XY1", "Beispielbeleg")
    assert (year, parsed.belegart, parsed.year) == (2025, "XY1", 2025)
    assert [f.text for f in parsed.fields] == ["7"]


def test_document_without_period_is_rejected() -> None:
    with pytest.raises(ReadInError, match="keinen Bezugszeitraum"):
        parse_elster_document(make_document(None), HEAD + ROW, "XY1", "Beispielbeleg")


def test_other_belegart_names_the_document_kind_and_the_belegart() -> None:
    with pytest.raises(ReadInError, match=r"Dokumentart Beispielbeleg.*Belegart XY1 fehlt"):
        parse_elster_document(
            make_document(), b"<!-- Belegart: E10 -->" + ROW, "XY1", "Beispielbeleg"
        )


def test_year_in_the_head_must_match_the_document() -> None:
    with pytest.raises(ReadInError, match="gehört zum Steuerjahr 2025, eingetragen ist 2024"):
        parse_elster_document(make_document(2024), HEAD + ROW, "XY1", "Beispielbeleg")


def test_head_without_year_is_accepted() -> None:
    head = b"<!-- Belegart: XY1 --><!-- Veranlagungsjahr: -->"
    year, parsed = parse_elster_document(make_document(2024), head + ROW, "XY1", "Beispielbeleg")
    assert (year, parsed.year) == (2024, None)
