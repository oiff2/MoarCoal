"""Aussteller-Liste mit Jahresmatrix: Zeichen je Jahr, Filter, Anzahlen, Seite (nur tmp_path)."""

import datetime
import hashlib
import re
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.issuer_years import (
    IssuerFilter,
    IssuerRow,
    Mark,
    apply_filter,
    counts,
    issuer_rows,
    own_first,
    parse_filter,
    search,
    years_shown,
)
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.storage import (
    COMMON_OWNER,
    Document,
    Entry,
    ExpectedDocument,
    Issuer,
    Put,
    open_store,
)

THIS = datetime.date.today().year
PORT = 4711


def bank(name: str = "Musterbank eG", **fields: object) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, **fields)  # pyright: ignore[reportArgumentType]


def paper(at: Issuer, year: int, kind: str = "bescheinigung", n: int = 0) -> Document:
    sha = hashlib.sha256(f"{kind}{year}{n}".encode()).hexdigest()
    return Document(
        owner="anna",
        site="Ablage",
        path=f"{kind}-{year}-{n}.pdf",
        sha256=sha,
        issuer=at.address,
        document_kind=kind,
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
    )


def expect(kind: str, start: int, end: int | None = None) -> ExpectedDocument:
    return ExpectedDocument(owner="anna", document_kind=kind, start_year=start, end_year=end)


def rows_of(tmp_path: Path, *entries: Entry) -> list[IssuerRow]:
    store = open_store(tmp_path, [])
    store.apply([Put(e) for e in entries])
    return issuer_rows(store.state(), "anna", store.sites, THIS)


def marks(row: IssuerRow) -> dict[int, Mark]:
    return dict(row.marks)


def test_years_end_with_the_current_year() -> None:
    years = years_shown(2026)
    assert years[0] == 2017 and years[-1] == 2026 and len(years) == 10


def test_without_expectations_a_document_year_is_present_else_none(tmp_path: Path) -> None:
    b = bank()
    (row,) = rows_of(tmp_path, b, paper(b, THIS - 1))
    assert marks(row)[THIS - 1] is Mark.PRESENT
    assert marks(row)[THIS - 2] is Mark.NONE
    assert row.documents == 1


def test_expected_missing_partial_and_met(tmp_path: Path) -> None:
    b = bank()
    entries = [
        b,
        paper(b, THIS - 3, "bescheinigung"),
        paper(b, THIS - 3, "freistellung"),
        paper(b, THIS - 2, "bescheinigung"),
        expect("bescheinigung", THIS - 3),
        expect("freistellung", THIS - 3),
    ]
    (row,) = rows_of(tmp_path, *entries)
    got = marks(row)
    assert got[THIS - 3] is Mark.PRESENT  # beide erfüllt
    assert got[THIS - 2] is Mark.PARTIAL  # Vorjahr trug beide, nur einer da
    assert got[THIS - 1] is Mark.MISSING  # nichts da, beide erwartet
    assert got[THIS - 4] is Mark.NONE  # vor Beginn nichts erwartet


def test_an_expectation_of_another_issuer_does_not_count(tmp_path: Path) -> None:
    a, b = bank("Musterbank eG"), bank("Beispielkasse AG")
    rows = rows_of(tmp_path, a, b, paper(a, THIS - 1), expect("bescheinigung", THIS - 1))
    by_name = {r.issuer.name: marks(r) for r in rows}
    assert by_name["Beispielkasse AG"][THIS - 1] is Mark.NONE
    assert by_name["Musterbank eG"][THIS - 1] is Mark.PRESENT


def test_sorted_by_documents_descending_then_name(tmp_path: Path) -> None:
    a, b, c = bank("Zeta"), bank("Alfa"), bank("Beta")
    rows = rows_of(tmp_path, a, b, c, paper(a, THIS, n=1), paper(a, THIS, n=2), paper(c, THIS))
    assert [r.issuer.name for r in rows] == ["Zeta", "Beta", "Alfa"]


def test_filters_and_counts(tmp_path: Path) -> None:
    recent = bank("Neu", portal="https://portal.example.org")
    old = bank("Alt")
    rows = rows_of(tmp_path, recent, old, paper(recent, THIS - 1), paper(old, THIS - 5))
    found = counts(rows)
    assert (found.all, found.no_documents, found.portal) == (2, 1, 1)
    assert [r.issuer.name for r in apply_filter(rows, IssuerFilter.NO_DOCUMENTS)] == ["Alt"]
    assert [r.issuer.name for r in apply_filter(rows, IssuerFilter.PORTAL)] == ["Neu"]
    assert apply_filter(rows, IssuerFilter.ALL) == rows
    assert parse_filter("unfug") is IssuerFilter.ALL


def test_search_matches_name_and_alias_only(tmp_path: Path) -> None:
    b = bank(aliases=("MB",), note="Geheimwort")
    rows = rows_of(tmp_path, b)
    assert search(rows, "musterbank") and search(rows, "mb")
    assert not search(rows, "geheimwort")


def make_client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, modules=[WORK, TAX_YEAR], user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_page_shows_matrix_chips_legend_and_keeps_filter_in_the_address(tmp_path: Path) -> None:
    recent = bank("Neu", portal="https://portal.example.org")
    old = bank("Alt")
    open_store(tmp_path, []).apply(
        [Put(e) for e in (recent, old, paper(recent, THIS - 1), paper(old, THIS - 5))]
    )
    client = make_client(tmp_path)

    page = client.get("/aussteller").text
    assert f'<th class="jahr">{THIS}</th>' in page
    assert f"ohne Belege seit {THIS - 1}" in page and "mit Portal" in page
    assert "Die Angaben zum Aussteller gelten für alle Steuerjahre" in page
    assert "Legende" in page and "erwartet, fehlt" in page

    only = client.get("/aussteller?filter=ohne-belege").text
    assert "Alt</a>" in only and "Neu</a>" not in only
    assert 'name="filter" value="ohne-belege"' in only
    portal = client.get("/aussteller?filter=portal&q=neu").text
    assert "Neu</a>" in portal and "Alt</a>" not in portal
    assert re.search(r'href="/aussteller\?q=neu"[^>]*aria-pressed="false"', portal)
    assert client.get("/aussteller?filter=portal&q=nix").text.count("Kein Aussteller") == 1


def test_own_issuer_stands_first_in_search_and_filter(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    own, big = bank("Max Zeta", private_person=True), bank("Beispielkasse AG")
    store.apply([Put(e) for e in (own, big, paper(big, THIS), paper(big, THIS, n=1))])
    rows = issuer_rows(store.state(), "anna", store.sites, THIS)
    assert [r.issuer.name for r in own_first(rows, own)] == ["Max Zeta", "Beispielkasse AG"]
    assert [r.issuer.name for r in own_first(rows, None)] == ["Beispielkasse AG", "Max Zeta"]
    both = search(rows, "a")  # passt auf beide
    assert [r.issuer.name for r in own_first(both, own)][0] == "Max Zeta"
    only_big = search(rows, "kasse")
    assert [r.issuer.name for r in own_first(only_big, own)] == ["Beispielkasse AG"]
    filtered = apply_filter(rows, IssuerFilter.NO_DOCUMENTS)  # nur der eigene besteht
    assert [r.issuer.name for r in own_first(filtered, own)] == ["Max Zeta"]
