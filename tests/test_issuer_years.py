"""Aussteller-Liste mit Jahresmatrix: Zeichen je Jahr, Filter, Anzahlen, Seite (nur tmp_path)."""

import datetime
import hashlib
import re
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.issuer_years import (
    YEARS_SHOWN,
    IssuerFilter,
    IssuerRow,
    Mark,
    issuer_detail,
    issuer_rows,
    listed,
    years_shown,
)
from moarcoal.modules.provision import REGISTRATION as PROVISION
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
    return {m.year: m.mark for m in row.marks}


def names(shown: tuple[list[IssuerRow], object]) -> list[str]:
    return [r.issuer.name for r in shown[0]]


def counted(row: IssuerRow) -> dict[int, int]:
    return {m.year: m.documents for m in row.marks}


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
    shown, found = listed(rows, "", IssuerFilter.ALL, None)
    assert shown == rows
    assert (found.all, found.no_documents, found.portal) == (2, 1, 1)
    assert names(listed(rows, "", IssuerFilter.NO_DOCUMENTS, None)) == ["Alt"]
    assert names(listed(rows, "", IssuerFilter.PORTAL, None)) == ["Neu"]
    _, within_search = listed(rows, "neu", IssuerFilter.NO_DOCUMENTS, None)
    assert (within_search.all, within_search.no_documents, within_search.portal) == (1, 0, 1)
    assert IssuerFilter.parse("unfug") is IssuerFilter.ALL


def test_search_matches_name_and_alias_only(tmp_path: Path) -> None:
    b = bank(aliases=("MB",), note="Geheimwort")
    rows = rows_of(tmp_path, b)
    assert names(listed(rows, "musterbank", IssuerFilter.ALL, None)) == ["Musterbank eG"]
    assert names(listed(rows, "mb", IssuerFilter.ALL, None)) == ["Musterbank eG"]
    assert names(listed(rows, "geheimwort", IssuerFilter.ALL, None)) == []


def make_client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, modules=[WORK, PROVISION, TAX_YEAR], user="anna")
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
    every = IssuerFilter.ALL
    assert names(listed(rows, "", every, own)) == ["Max Zeta", "Beispielkasse AG"]
    assert names(listed(rows, "", every, None)) == ["Beispielkasse AG", "Max Zeta"]
    assert names(listed(rows, "a", every, own))[0] == "Max Zeta"  # passt auf beide
    assert names(listed(rows, "kasse", every, own)) == ["Beispielkasse AG"]
    # nur der eigene besteht den Filter
    assert names(listed(rows, "", IssuerFilter.NO_DOCUMENTS, own)) == ["Max Zeta"]


def test_detail_lists_years_descending_with_missing_expected_documents(tmp_path: Path) -> None:
    b = bank()
    store = open_store(tmp_path, [])
    store.apply(
        [
            Put(e)
            for e in (
                b,
                paper(b, THIS - 2, "bescheinigung"),
                paper(b, THIS - 2, "freistellung"),
                paper(b, THIS - 4, "bescheinigung"),
                expect("bescheinigung", THIS - 4),
                expect("freistellung", THIS - 2),
            )
        ]
    )
    detail = issuer_detail(store.state(), "anna", store.sites, b, THIS)
    assert detail.documents == 3 and detail.years_with_documents == 2
    years = [y.year for y in detail.years]
    assert years == sorted(years, reverse=True)
    by_year = {y.year: y for y in detail.years}
    assert len(by_year[THIS - 2].documents) == 2 and not by_year[THIS - 2].missing
    assert [e.document_kind for e in by_year[THIS - 1].missing] == ["bescheinigung", "freistellung"]
    assert not by_year[THIS - 1].documents
    assert THIS - 3 in by_year  # Bescheinigung des Vorjahrs erwartet, fehlt
    assert detail.without_year == ()


def test_detail_puts_documents_without_a_year_aside(tmp_path: Path) -> None:
    b = bank()
    loose = Document(
        owner="anna", site="Ablage", path="lose.pdf", sha256="d" * 64, issuer=b.address
    )
    store = open_store(tmp_path, [])
    store.apply([Put(b), Put(loose)])
    detail = issuer_detail(store.state(), "anna", store.sites, b, THIS)
    assert detail.documents == 1 and detail.years == () and detail.without_year == (loose,)


def test_page_selects_the_issuer_keeps_search_and_shows_the_years(tmp_path: Path) -> None:
    b, other = bank(portal="https://portal.example.org"), bank("Beispielkasse AG")
    open_store(tmp_path, []).apply(
        [Put(e) for e in (b, other, paper(b, THIS - 2), expect("bescheinigung", THIS - 2))]
    )
    client = make_client(tmp_path)

    plain = client.get("/aussteller").text
    assert "Einen Aussteller in der Liste wählen" in plain and not re.search(
        r'href="/aussteller/[^"]*" aria-current', plain
    )

    page = client.get(f"/aussteller/{b.id}?q=bank&filter=portal").text
    assert re.search(
        rf'href="/aussteller/{b.id}\?q=bank&amp;filter=portal"[^>]*aria-current="page"', page
    )
    assert "1 Beleg in 1 Jahr" in page
    assert 'href="https://portal.example.org"' in page and 'title="Portal öffnen"' in page
    assert f"<h3>{THIS - 2}</h3>" in page and f"bescheinigung-{THIS - 2}-0.pdf</a>" in page
    assert "bescheinigung · erwartet, fehlt" in page
    assert page.count('name="q" value="bank"') >= 2  # Suche und Speichern-Formular

    saved = client.post(
        f"/aussteller/{b.id}",
        data={
            "name": b.name,
            "q": "bank",
            "filter": "portal",
            "checksum": re.search(r'name="checksum" value="([0-9a-f]+)"', page).group(1),  # pyright: ignore[reportOptionalMemberAccess]
        },
        headers={"Origin": f"http://127.0.0.1:{PORT}"},
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == f"/aussteller/{b.id}?q=bank&filter=portal"


def test_a_cell_counts_the_documents_of_the_year_and_lists_the_missing_ones(
    tmp_path: Path,
) -> None:
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
    got = {m.year: m for m in row.marks}
    assert counted(row)[THIS - 3] == 2 and counted(row)[THIS - 2] == 1
    assert counted(row)[THIS - 1] == 0 and counted(row)[THIS - 4] == 0
    assert got[THIS - 3].missing == ()
    assert [e.document_kind for e in got[THIS - 2].missing] == ["freistellung"]
    assert [e.document_kind for e in got[THIS - 1].missing] == ["bescheinigung"]


def test_a_multi_year_document_counts_in_each_cell_but_once_in_the_total(tmp_path: Path) -> None:
    b = bank()
    long = Document(
        owner="anna",
        site="Ablage",
        path="mehrjahr.pdf",
        sha256=hashlib.sha256(b"mehrjahr").hexdigest(),
        issuer=b.address,
        document_kind="bescheinigung",
        period_start=datetime.date(THIS - 2, 1, 1),
        period_end=datetime.date(THIS - 1, 12, 31),
    )
    (row,) = rows_of(tmp_path, b, long, paper(b, THIS - 1))
    assert counted(row)[THIS - 2] == 1 and counted(row)[THIS - 1] == 2
    assert row.documents == 2  # nicht 3: das Mehrjahres-Dokument zählt einmal


def test_documents_outside_the_shown_years_do_not_count_in_the_total(tmp_path: Path) -> None:
    b = bank()
    before = THIS - YEARS_SHOWN
    straddling = Document(
        owner="anna",
        site="Ablage",
        path="grenze.pdf",
        sha256=hashlib.sha256(b"grenze").hexdigest(),
        issuer=b.address,
        document_kind="bescheinigung",
        period_start=datetime.date(before, 1, 1),
        period_end=datetime.date(before + 1, 12, 31),
    )
    (row,) = rows_of(tmp_path, b, paper(b, before), paper(b, THIS), straddling)
    assert row.documents == 2  # THIS und das Dokument, das ins erste gezeigte Jahr reicht
    assert sum(counted(row).values()) == 2


def test_missing_expected_documents_are_yellow_like_the_tax_year_stage(tmp_path: Path) -> None:
    b = bank()
    open_store(tmp_path, []).apply(
        [Put(e) for e in (b, paper(b, THIS - 2), expect("bescheinigung", THIS - 2))]
    )
    page = make_client(tmp_path).get(f"/aussteller/{b.id}").text
    assert 'class="status status-warning jahresmarke-missing"' in page
    assert 'class="status status-warning jahresmarke-partial"' in page  # Legende
    assert "jahresmarke" in page and not re.search(r"status-error[^\"]*jahresmarke", page)
    assert '<span class="status status-pending"' in page  # Detail: ○ erwartet, fehlt
    assert f'action="/aussteller/{b.id}/loeschen"' not in page  # verweist noch: kein Löschen
    assert f'action="/aussteller/{b.id}/zusammenfuehren"' not in page  # kein anderer Aussteller
