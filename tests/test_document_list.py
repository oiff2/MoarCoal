"""Tests: aufgenommene Belege der Seite (Zustand), Ändern und Löschen (nur tmp_path)."""

import datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient
from test_belege_year import section

from moarcoal.storage import (
    COMMON_OWNER,
    Document,
    Issuer,
    Proposal,
    ProposalField,
    Put,
    State,
    Store,
    entry_checksum,
)
from moarcoal.storage.entries import Entry
from moarcoal.web.links import document_url

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    (folder / "2025" / "protokoll.html").write_bytes(FIXTURE.read_bytes())
    (folder / "bescheid.txt").write_text("Beispiel", encoding="utf-8")
    return folder


@pytest.fixture
def client(tmp_path: Path, site: Path) -> httpx.Client:
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def state_of(client: httpx.Client) -> State:
    return store_of(client).state()


def documents(client: httpx.Client) -> list[Document]:
    return sorted(state_of(client).of_kind(Document), key=lambda d: d.path)


def take(client: httpx.Client, path_sha: str, **fields: str) -> None:
    data = {"sha256": path_sha, "kind": "transfer_protocol", "year": "2025", **fields}
    assert client.post("/belege/aufnehmen", data=data, headers=ORIGIN).status_code == 303


def doc(client: httpx.Client, name: str) -> Document:
    return next(d for d in documents(client) if d.path.endswith(name))


def add_issuer(client: httpx.Client, name: str) -> Issuer:
    issuer = Issuer(owner=COMMON_OWNER, name=name)
    store_of(client).apply([Put(issuer)])
    return issuer


def main_of(client: httpx.Client, url: str) -> str:
    return client.get(url).text.split("<main>")[1]


def change(client: httpx.Client, document: Document, **fields: str) -> httpx.Response:
    return client.post(f"/dokumente/{document.id}/aendern", data=fields, headers=ORIGIN)


def delete(client: httpx.Client, document: Document, checksum: str) -> httpx.Response:
    data = {"checksum": checksum}
    return client.post(f"/dokumente/{document.id}/loeschen", data=data, headers=ORIGIN)


@pytest.fixture
def two(client: httpx.Client, site: Path) -> httpx.Client:
    """Das Protokoll (mit Einlesung) und ein Bescheid ohne Verweise (Art Einkommensteuerbescheid),
    Aussteller nur am Bescheid."""
    bank = add_issuer(client, "Beispielbank AG")
    take(client, SHA)
    take(
        client,
        hashlib.sha256((site / "bescheid.txt").read_bytes()).hexdigest(),
        kind="assessment",
        issuer_choice=f"id:{bank.id}",
    )
    return client


# --- Seite, Zustand ----------------------------------------------------------------


def taken_in(client: httpx.Client) -> str:
    """Der Abschnitt Aufgenommene Belege der Seite."""
    return section(main_of(client, "/belege"), "aufgenommen")


def test_section_lists_the_documents_with_state_and_get_writes_nothing(two: httpx.Client) -> None:
    before = state_of(two)
    page = taken_in(two)
    assert "protokoll.html" in page and "bescheid.txt" in page
    assert "Aufgenommene Belege (2)" in main_of(two, "/belege")
    assert page.count('<span class="stand">fertig</span>') == 1  # das eingelesene Protokoll
    assert page.count('<span class="stand">auszulesen</span>') == 1  # der Bescheid
    assert state_of(two) == before


def test_kind_with_template_and_no_proposal_is_to_extract(two: httpx.Client) -> None:
    """Ein nie ausgelesener Bescheid ist nicht „fertig“, sondern „auszulesen“; das Protokoll hat
    keine Auslese-Vorlage und ist fertig."""
    rows = taken_in(two).split('<div class="datei"')[1:]
    [bescheid] = [r for r in rows if "bescheid.txt" in r]
    [protocol] = [r for r in rows if "protokoll.html" in r]
    assert '<span class="stand">auszulesen</span>' in bescheid
    assert '<span class="stand">fertig</span>' in protocol


def test_state_is_to_confirm_while_a_proposal_has_open_fields(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    proposal = Proposal(
        owner="anna",
        document=bescheid.address,
        template_version=1,
        fields={"x": ProposalField(value="1", location="S. 1")},
        raw="{}",
        created_at=datetime.datetime.now(datetime.UTC),
    )
    store_of(two).apply([Put(proposal)])
    assert '<span class="stand">zu bestätigen</span>' in taken_in(two)
    confirmed = proposal.model_copy(
        update={"fields": {"x": proposal.fields["x"].model_copy(update={"confirmed": True})}}
    )
    store_of(two).apply([Put(confirmed, entry_checksum(proposal))])
    page = taken_in(two)
    assert '<span class="stand">zu bestätigen</span>' not in page
    assert page.count('<span class="stand">fertig</span>') == 2


def test_document_without_kind_has_no_period_and_so_belongs_to_no_year_here(
    two: httpx.Client,
) -> None:
    bescheid = doc(two, "bescheid.txt")
    assert change(two, bescheid, kind="", issuer_choice="").status_code == 303
    after = doc(two, "bescheid.txt")
    assert after.document_kind is None and after.period_start is None
    assert "bescheid.txt" not in taken_in(two)  # ohne Zeitraum an einem Ablageort ohne Jahr
    assert "bescheid.txt" in main_of(two, document_url(after.id))  # die Seite zeigt es trotzdem


def test_detail_shows_form_with_preview_and_locks_when_something_hangs(
    two: httpx.Client,
) -> None:
    protocol, bescheid = doc(two, "protokoll.html"), doc(two, "bescheid.txt")
    locked = main_of(two, f"/belege?dokument={protocol.id}")
    assert "gesperrt" in locked and "Einlesung" in locked
    assert 'name="kind" disabled' in locked
    assert "Dokument löschen" in locked  # Einlesung fällt mit weg, Schnappschuss sperrt nicht
    assert f"/dokumente/{protocol.id}/datei" in locked
    assert f'href="/dokumente/{protocol.id}">Dokument</a>' not in locked  # kein Link je Zeile
    assert "Einträge mit diesem Beleg" in locked  # die Detailspalte, auf der Seite
    free = main_of(two, f"/belege?dokument={bescheid.id}")
    assert "gesperrt" not in free and "disabled" not in free and "Dokument löschen" in free


def test_old_document_address_redirects_to_the_page(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    old = two.get(f"/dokumente/{bescheid.id}")
    assert old.status_code == 308
    assert old.headers["location"] == document_url(bescheid.id) == f"/belege?dokument={bescheid.id}"
    protocol = doc(two, "protokoll.html")
    assert two.get(f"/dokumente/{protocol.id}/datei").status_code == 200  # die Datei bleibt


def tab_of(response: httpx.Response) -> str:
    """Die Belege-Seite einer Antwort: das gewählte Dokument rechts."""
    return response.text.split("<main>")[1].split('<div class="rechts" id="detailspalte">')[1]


# --- Ändern ---------------------------------------------------------------------------------


def test_refused_change_shows_the_tab_with_the_document_reason_and_input(
    two: httpx.Client,
) -> None:
    bescheid = doc(two, "bescheid.txt")
    response = change(two, bescheid, issuer_choice="", kind="assessment", year="zwanzig")
    assert response.status_code == 422
    right = tab_of(response)
    assert "bescheid.txt" in right and f"/dokumente/{bescheid.id}/aendern" in right
    assert '<p class="fehler">Steuerjahr: ganze Zahl, z. B. 2025</p>' in right
    assert 'value="zwanzig"' in right


def test_refused_change_links_the_existing_document_on_the_page(
    two: httpx.Client, site: Path
) -> None:
    other = FIXTURE.read_bytes() + b"\n<!-- zweite Datei -->\n"  # lesbar als Protokoll
    (site / "zweites.html").write_bytes(other)
    take(two, hashlib.sha256(other).hexdigest(), kind="assessment", year="2024")
    protocol, second = doc(two, "protokoll.html"), doc(two, "zweites.html")
    response = change(two, second, issuer_choice="", kind="transfer_protocol", year="2025")
    assert response.status_code == 422
    right = tab_of(response)
    assert "Existiert bereits: Übertragungsprotokoll 2025" in right
    assert f'(<a href="{document_url(protocol.id)}">vorhandenes Dokument</a>)' in right


def test_issuer_changes_even_while_locked_and_keeps_kind_and_year(two: httpx.Client) -> None:
    protocol = doc(two, "protokoll.html")
    werke = add_issuer(two, "Stadtwerke Beispielstadt")
    response = change(two, protocol, issuer_choice=f"id:{werke.id}")
    assert response.status_code == 303
    assert response.headers["location"] == f"/belege?dokument={protocol.id}"
    after = doc(two, "protokoll.html")
    assert after.issuer == werke.address
    assert (after.document_kind, after.period_start) == (
        protocol.document_kind,
        protocol.period_start,
    )


def test_kind_and_year_are_refused_while_something_hangs(two: httpx.Client) -> None:
    protocol = doc(two, "protokoll.html")
    before = state_of(two)
    response = change(two, protocol, issuer_choice="", kind="assessment", year="2024")
    assert response.status_code == 422 and "gesperrt" in response.text
    assert state_of(two) == before


def test_year_changes_when_nothing_hangs(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    response = change(two, bescheid, issuer_choice="", kind="assessment", year="2024")
    assert response.status_code == 303
    after = doc(two, "bescheid.txt")
    assert after.period_start == datetime.date(2024, 1, 1)
    assert after.period_end == datetime.date(2024, 12, 31)
    assert after.issuer is None  # das Formular entscheidet über den Aussteller


def test_bad_year_is_rejected_and_keeps_state(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    before = state_of(two)
    assert change(two, bescheid, issuer_choice="", kind="assessment", year="x").status_code == 422
    assert (
        change(two, bescheid, issuer_choice="", kind="assessment", year="1900").status_code == 422
    )
    assert state_of(two) == before


def test_new_kind_reads_the_file_in_and_then_locks(client: httpx.Client) -> None:
    take(client, SHA, kind="assessment")
    document = doc(client, "protokoll.html")
    assert (
        change(
            client, document, issuer_choice="", kind="transfer_protocol", year="2025"
        ).status_code
        == 303
    )
    assert documents(client)[0].document_kind == "transfer_protocol"
    [reading] = [
        e for e in state_of(client).entries.values() if "ProtocolReading" in str(e.address)
    ]
    assert isinstance(reading, Entry)
    assert "gesperrt" in main_of(client, f"/belege?dokument={document.id}")


def test_new_kind_that_cannot_read_the_file_is_rejected(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")  # eine Textdatei, kein Übertragungsprotokoll
    before = state_of(two)
    response = change(two, bescheid, issuer_choice="", kind="transfer_protocol", year="2025")
    assert response.status_code == 422
    assert state_of(two) == before


def test_change_needs_origin(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    response = two.post(f"/dokumente/{bescheid.id}/aendern", data={"issuer_choice": ""})
    assert response.status_code == 403


# --- Löschen --------------------------------------------------------------------------------


def test_delete_removes_only_the_document_and_the_file_is_open_again(
    two: httpx.Client, site: Path
) -> None:
    bescheid = doc(two, "bescheid.txt")
    assert "bescheid.txt" not in section(main_of(two, "/belege"), "neu")
    response = delete(two, bescheid, entry_checksum(bescheid))
    assert response.status_code == 303 and response.headers["location"] == "/belege"
    assert [d.path for d in documents(two)] == ["2025/protokoll.html"]
    assert (site / "bescheid.txt").exists()
    assert "bescheid.txt" in section(main_of(two, "/belege"), "neu")  # wieder offen
    assert len(list(state_of(two).of_kind(Issuer))) == 1  # der Aussteller bleibt


def test_delete_takes_the_reading_along_and_the_file_can_be_taken_in_again(
    two: httpx.Client,
) -> None:
    protocol = doc(two, "protokoll.html")
    response = delete(two, protocol, entry_checksum(protocol))
    assert response.status_code == 303
    assert len(documents(two)) == 1
    assert not any(type(e).__name__ == "ProtocolReading" for e in state_of(two).entries.values())
    take(two, SHA)  # derselbe Inhalt, jetzt wieder frei
    assert len(documents(two)) == 2


def test_delete_is_refused_while_a_proposal_points_at_the_document(two: httpx.Client) -> None:
    protocol = doc(two, "protokoll.html")
    proposal = Proposal(
        owner="anna",
        document=protocol.address,
        template_version=1,
        fields={"x": ProposalField(value="1", location="S. 1")},
        raw="{}",
        created_at=datetime.datetime.now(datetime.UTC),
    )
    store_of(two).apply([Put(proposal)])
    page = main_of(two, f"/belege?dokument={protocol.id}")
    assert "Dokument löschen" not in page and "Vorschlag" in page
    response = delete(two, protocol, entry_checksum(protocol))
    assert response.status_code == 409 and "Wird noch verwendet." in response.text
    assert len(documents(two)) == 2


def test_delete_with_stale_checksum_is_refused_on_the_page(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    response = delete(two, bescheid, "alt")
    assert response.status_code == 409
    right = tab_of(response)
    assert "bescheid.txt" in right and '<p class="fehler">' in right
    assert len(documents(two)) == 2


def test_other_users_documents_are_not_listed(two: httpx.Client) -> None:
    foreign = doc(two, "protokoll.html").model_copy(update={"owner": "ben", "id": "ABCDEFGHIJ"})
    store_of(two).apply([Put(foreign)])
    assert "Aufgenommene Belege (2)" in main_of(two, "/belege")
    assert two.get(f"/dokumente/{foreign.id}/datei").status_code == 404
    assert f"/dokumente/{foreign.id}/aendern" not in main_of(two, document_url(foreign.id))


# --- Detailspalte (#185) -----------------------------------------------------------------


def test_detail_column_order_fields_entries_actions_then_the_file_view(two: httpx.Client) -> None:
    protocol = doc(two, "protokoll.html")
    right = tab_of(two.get(document_url(protocol.id)))
    marks = [
        f"/dokumente/{protocol.id}/aendern",  # Felder und Speichern
        "Einträge mit diesem Beleg",
        "Datei öffnen",
        "Dokument löschen",
        "<iframe",  # ganz unten die Dateiansicht
    ]
    positions = [right.index(m) for m in marks]
    assert positions == sorted(positions)
    assert ">Speichern<" in right
    assert f'href="/dokumente/{protocol.id}/datei"' in right  # Datei öffnen


def test_detail_column_lists_the_entries_of_the_document(two: httpx.Client) -> None:
    protocol = doc(two, "protokoll.html")
    entries = tab_of(two.get(document_url(protocol.id))).split("Einträge mit diesem Beleg")[1]
    assert "Einlesung" in entries.split("Datei öffnen")[0]
    free = tab_of(two.get(document_url(doc(two, "bescheid.txt").id)))
    assert "Kein Eintrag hängt an diesem Beleg." in free


def test_the_document_is_rendered_once_in_the_column(two: httpx.Client) -> None:
    bescheid = doc(two, "bescheid.txt")
    page = two.get(document_url(bescheid.id)).text
    assert page.count(f"/dokumente/{bescheid.id}/aendern") == 1
    assert page.count('class="vorschau"') == 1


def test_column_can_be_hidden_and_the_browser_remembers_it(two: httpx.Client) -> None:
    page = two.get("/belege").text
    assert "data-detailspalte-schalter" in page and "Detailspalte ausblenden" in page
    assert 'class="rechts" id="detailspalte"' in page
    js = Path("src/moarcoal/static/belege.js").read_text(encoding="utf-8")
    assert "localStorage" in js and "catch" in js  # nur Bequemlichkeit, die Seite geht ohne
    assert "http" not in js


def test_a_click_on_a_row_selects_it(two: httpx.Client) -> None:
    js = Path("src/moarcoal/static/belege.js").read_text(encoding="utf-8")
    assert "a.name" in js and 'closest("a, button, form, input, select, summary")' in js


def test_sections_remember_open_state_without_flicker(two: httpx.Client) -> None:
    page = two.get("/belege").text
    assert page.count('<details class="abschnitt"') == 3
    # Ohne defer hinter den Abschnitten: läuft vor der ersten Darstellung (kein Flackern).
    assert '<script src="/static/belege.js"></script>' in page
    js = Path("src/moarcoal/static/belege.js").read_text(encoding="utf-8")
    assert "details.abschnitt" in js and '"toggle"' in js and "a[aria-current]" in js
    assert "http" not in js
