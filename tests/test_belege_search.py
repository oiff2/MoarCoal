"""Tests: Suche und Dateityp-Filter oben auf der Belege-Seite (#186; nur tmp_path)."""

from pathlib import Path

import httpx
import pytest
from test_belege_year import KIND, ORIGIN, main_of, make_client, section, sha, store_of, take

from moarcoal.document_filter import FileType, SearchFilter
from moarcoal.storage import (
    COMMON_OWNER,
    Document,
    ExpectedDocument,
    HiddenFile,
    Issuer,
    Put,
    entry_checksum,
)
from moarcoal.web.links import site_url, with_filter


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    year = tmp_path / "steuer25"
    (year / "bank").mkdir(parents=True)
    for name in ("miete.pdf", "foto.png", "liste.xlsx", "notiz.txt", "bank/auszug.PDF"):
        (year / name).write_text(name)
    return make_client(tmp_path, {"steuer25": year})


def counted(client: httpx.Client, url: str, name: str, title: str) -> int:
    """Die Zahl im Titel des Abschnitts `name` der Seite `url`."""
    page = main_of(client, url)
    assert f"<summary>{title} (" in section(page, name)
    return int(section(page, name).split(f"<summary>{title} (")[1].split(")")[0])


def test_site_url_carries_search_and_types() -> None:
    assert site_url(query="miete", types=["pdf", "bild"]) == "/belege?suche=miete&typ=pdf&typ=bild"
    assert site_url(year=2025, query="a b") == "/belege?jahr=2025&suche=a+b"
    assert site_url(query="  ") == "/belege"


def test_search_narrows_new_files_by_name_and_folder_without_case(client: httpx.Client) -> None:
    neu = section(main_of(client, "/belege?suche=MIETE"), "neu")
    assert "miete.pdf" in neu and "foto.png" not in neu
    assert counted(client, "/belege?suche=bank", "neu", "Neu im Jahresordner") == 1


def test_type_filter_is_a_multiple_choice_and_counts_ignore_the_type_choice(
    client: httpx.Client,
) -> None:
    page = main_of(client, "/belege?typ=pdf&typ=bild")
    neu = section(page, "neu")
    assert "miete.pdf" in neu and "auszug.PDF" in neu and "foto.png" in neu
    assert "liste.xlsx" not in neu and "notiz.txt" not in neu
    for label, count in (("PDF", 2), ("Bild", 1), ("Tabelle", 1), ("Sonstiges", 1), ("eDaten", 0)):
        assert f"{label} ({count})" in page


def test_counts_follow_the_search(client: httpx.Client) -> None:
    page = main_of(client, "/belege?suche=miete")
    assert "PDF (1)" in page and "Bild (0)" in page


def test_search_and_choice_stay_in_the_form(client: httpx.Client) -> None:
    page = main_of(client, "/belege?suche=miete&typ=pdf")
    assert 'name="suche" value="miete"' in page
    assert 'value="pdf" checked' in page
    assert 'value="bild" checked' not in page


def test_selecting_a_file_keeps_search_and_types(client: httpx.Client) -> None:
    neu = section(main_of(client, "/belege?suche=miete&typ=pdf"), "neu")
    assert f'href="/belege?datei={sha("miete.pdf")}&amp;suche=miete&amp;typ=pdf"' in neu


def test_taken_in_documents_are_searched_by_issuer_label_and_folder_and_filtered_by_type(
    client: httpx.Client,
) -> None:
    store = store_of(client)
    stadtwerke = Issuer(owner=COMMON_OWNER, name="Stadtwerke Beispiel")
    store.apply([Put(stadtwerke)])
    take(client, "miete.pdf", label="Strom")
    take(client, "foto.png", label="Dachschaden")
    take(client, "bank/auszug.PDF")
    document = next(d for d in store.state().of_kind(Document) if d.path == "miete.pdf")
    issued = document.model_copy(update={"issuer": stadtwerke.address})
    store.apply([Put(issued, expected=entry_checksum(document))])
    for query in ("stadtwerke", "dachschaden", "bank"):
        assert counted(client, f"/belege?suche={query}", "aufgenommen", "Aufgenommene Belege") == 1
    assert counted(client, "/belege?typ=bild", "aufgenommen", "Aufgenommene Belege") == 1
    assert counted(client, "/belege?typ=pdf", "aufgenommen", "Aufgenommene Belege") == 2
    assert counted(client, "/belege?typ=tabelle", "aufgenommen", "Aufgenommene Belege") == 0


def test_expected_documents_are_searched_by_text_and_pending_ones_have_no_file_type(
    client: httpx.Client,
) -> None:
    entry = ExpectedDocument(
        owner="anna",
        document_kind=KIND,
        start_year=2025,
        end_year=2025,
        description="Jahresabrechnung Nebenkosten",
    )
    store_of(client).apply([Put(entry)])
    assert counted(client, "/belege?suche=nebenkosten", "erwartet", "Erwartete Belege") == 1
    assert counted(client, "/belege?suche=quatsch", "erwartet", "Erwartete Belege") == 0
    assert counted(client, "/belege?typ=pdf", "erwartet", "Erwartete Belege") == 0


def test_unknown_types_are_ignored_and_get_changes_nothing(client: httpx.Client) -> None:
    before = store_of(client).state()
    assert "miete.pdf" in section(main_of(client, "/belege?typ=quatsch"), "neu")
    assert store_of(client).state() == before


# --- Suche und Filter bleiben beim Navigieren stehen -------------------------------------------

FILTER = "suche=miete&typ=pdf"
FILTER_HTML = FILTER.replace("&", "&amp;")


def location(response: httpx.Response) -> str:
    assert response.status_code == 303
    return response.headers["location"]


def test_with_filter_appends_to_any_address_before_the_fragment() -> None:
    flt = SearchFilter("a b", frozenset({FileType.PDF}))
    assert with_filter("/belege?dokument=X", flt) == "/belege?dokument=X&suche=a+b&typ=pdf"
    assert with_filter("/belege#erwartet", flt) == "/belege?suche=a+b&typ=pdf#erwartet"
    assert with_filter("/belege", SearchFilter()) == "/belege"


def test_clicking_a_document_keeps_the_filter(client: httpx.Client) -> None:
    take(client, "miete.pdf")
    document = next(iter(store_of(client).state().of_kind(Document)))
    page = main_of(client, f"/belege?{FILTER}")
    assert f'href="/belege?dokument={document.id}&amp;{FILTER_HTML}"' in page
    # die Seite des gewählten Dokuments behält Suche und Wahl in Formular und Aktionen
    chosen = main_of(client, f"/belege?dokument={document.id}&{FILTER}")
    assert 'name="suche" value="miete"' in chosen and 'value="pdf" checked' in chosen
    assert f'action="/dokumente/{document.id}/aendern?{FILTER_HTML}"' in chosen


def test_taking_in_and_hiding_redirect_with_the_filter(client: httpx.Client) -> None:
    data = {"sha256": sha("miete.pdf"), "kind": "", "year": "2025"}
    chosen = main_of(client, f"/belege?datei={sha('foto.png')}&{FILTER}")
    assert f'action="/belege/aufnehmen?{FILTER_HTML}"' in chosen
    out = client.post(f"/belege/aufnehmen?{FILTER}", data=data, headers=ORIGIN)
    assert "datei=" in location(out) and location(out).endswith(FILTER)  # weiter zur nächsten
    hide = client.post(
        f"/belege/ausblenden?{FILTER}", data={"sha256": sha("foto.png")}, headers=ORIGIN
    )
    assert location(hide).endswith(FILTER)
    direct = client.post(
        f"/belege/ausblenden-direkt?{FILTER}", data={"sha256": sha("notiz.txt")}, headers=ORIGIN
    )
    assert location(direct) == f"/belege?{FILTER}"


def test_showing_again_and_removing_an_expected_document_redirect_with_the_filter(
    client: httpx.Client,
) -> None:
    client.post("/belege/ausblenden-direkt", data={"sha256": sha("notiz.txt")}, headers=ORIGIN)
    hidden = store_of(client).state().of_kind(HiddenFile)[0]
    back = client.post(
        f"/belege/einblenden?{FILTER}",
        data={"sha256": hidden.sha256, "checksum": entry_checksum(hidden)},
        headers=ORIGIN,
    )
    assert location(back) == f"/belege?{FILTER}"
    entry = ExpectedDocument(owner="anna", document_kind=KIND, start_year=2025, end_year=2025)
    store_of(client).apply([Put(entry)])
    removed = client.post(
        f"/belege/erwartet/{entry.id}/loeschen?{FILTER}",
        data={"checksum": entry_checksum(entry)},
        headers=ORIGIN,
    )
    assert location(removed) == f"/belege?{FILTER}#erwartet"


def test_document_actions_redirect_with_the_filter(client: httpx.Client) -> None:
    take(client, "miete.pdf")
    document = next(iter(store_of(client).state().of_kind(Document)))
    changed = client.post(
        f"/dokumente/{document.id}/aendern?{FILTER}",
        data={"kind": "", "year": "2025", "label": "Neu"},
        headers=ORIGIN,
    )
    assert location(changed) == f"/belege?dokument={document.id}&{FILTER}"
    current = next(iter(store_of(client).state().of_kind(Document)))
    gone = client.post(
        f"/dokumente/{document.id}/loeschen?{FILTER}",
        data={"checksum": entry_checksum(current)},
        headers=ORIGIN,
    )
    assert location(gone) == f"/belege?{FILTER}"
