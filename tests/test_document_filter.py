"""Tests: Dateityp und Suchfilter der Belege-Seite (#186; reine Funktionen)."""

import pytest

from moarcoal.document_filter import FileType, SearchFilter, file_type, parse_file_types


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/Rechnung.PDF", FileType.PDF),
        ("elster/bescheid.html", FileType.EDATEN),
        ("elster/bescheid.xml", FileType.EDATEN),
        ("foto.jpeg", FileType.IMAGE),
        ("scan.png", FileType.IMAGE),
        ("liste.xlsx", FileType.TABLE),
        ("liste.ods", FileType.TABLE),
        ("liste.csv", FileType.TABLE),
        ("notiz.txt", FileType.OTHER),
        ("ohneendung", FileType.OTHER),
    ],
)
def test_file_type_by_extension(path: str, expected: FileType) -> None:
    assert file_type(path) is expected


def test_parse_file_types_ignores_unknown_values() -> None:
    assert parse_file_types(["pdf", "bild", "quatsch"]) == {FileType.PDF, FileType.IMAGE}


def test_empty_filter_lets_everything_through_even_without_a_file() -> None:
    flt = SearchFilter()
    assert not flt.active
    assert flt.matches([], [])


def test_search_ignores_case_and_matches_any_text() -> None:
    flt = SearchFilter(query="  MIET ")
    assert flt.active
    assert flt.matches(["Scans", "vertraege/mietvertrag.pdf"], [FileType.PDF])
    assert not flt.matches(["Scans", "vertraege/kaufvertrag.pdf"], [FileType.PDF])


def test_several_types_are_an_or_and_an_item_without_file_drops_out() -> None:
    flt = SearchFilter(types=frozenset({FileType.PDF, FileType.IMAGE}))
    assert flt.matches(["x"], [FileType.IMAGE])
    assert not flt.matches(["x"], [FileType.TABLE])
    assert not flt.matches(["x"], [])


def test_search_and_type_must_both_hold() -> None:
    flt = SearchFilter("bank", frozenset({FileType.PDF}))
    assert flt.matches(["bank"], [FileType.PDF])
    assert not flt.matches(["bank"], [FileType.IMAGE])
    assert not flt.matches(["post"], [FileType.PDF])
    assert flt.without_types().matches(["bank"], [FileType.IMAGE])
