"""Tests: Aussteller-Feld beim Aufnehmen und am Dokument (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.issuer_field import IssuerChoice, last_issuer, resolve_issuer, search_issuers
from moarcoal.storage import COMMON_OWNER, Document, Issuer, Put, State

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    site = tmp_path / "ablage"
    (site / "2025").mkdir(parents=True)
    (site / "2025" / "protokoll.html").write_bytes(FIXTURE.read_bytes())
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = create_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def state_of(client: httpx.Client) -> State:
    return client.app.state.store.state()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def add_issuer(client: httpx.Client, name: str = "Beispielbank AG", **fields: object) -> Issuer:
    issuer = Issuer(owner=COMMON_OWNER, name=name, **fields)  # pyright: ignore[reportArgumentType]
    client.app.state.store.apply([Put(issuer)])  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    return issuer


def take(client: httpx.Client, **extra: str) -> httpx.Response:
    data = {"sha256": SHA, "kind": "transfer_protocol", "year": "2025", **extra}
    return client.post("/belege/aufnehmen", data=data, headers=ORIGIN)


def only_document(client: httpx.Client) -> Document:
    return state_of(client).of_kind(Document)[0]


def issuers(client: httpx.Client) -> list[Issuer]:
    return state_of(client).of_kind(Issuer)


# --- Suche -------------------------------------------------------------------------------------


def test_search_finds_by_name_and_alias_ignoring_case(client: httpx.Client) -> None:
    add_issuer(client, "Beispielbank AG", aliases=("Sparkasse Muster",))
    add_issuer(client, "Stadtwerke Beispielstadt")
    state = state_of(client)
    assert [i.name for i in search_issuers(state, "BEISPIELBANK")] == ["Beispielbank AG"]
    assert [i.name for i in search_issuers(state, "sparkasse")] == ["Beispielbank AG"]
    assert [i.name for i in search_issuers(state, "stadtwerke")] == ["Stadtwerke Beispielstadt"]
    assert search_issuers(state, "  ") == []
    assert search_issuers(state, "Gibtsnicht") == []


def test_search_endpoint_offers_hit_and_alias_and_writes_nothing(client: httpx.Client) -> None:
    bank = add_issuer(client, "Beispielbank AG")
    before = state_of(client)
    html = client.get("/aussteller-suche", params={"issuer_text": "beispielbank ag filiale"}).text
    assert f'"issuer_choice": "id:{bank.id}"' in html
    assert "Beispielbank AG" in html
    assert "Neuer Alias: „beispielbank ag filiale“ zu Beispielbank AG" in html
    assert 'name="issuer_choice"' not in html  # nichts gewählt
    assert "Neu anlegen" not in html and 'type="radio"' not in html
    assert state_of(client) == before


def test_search_endpoint_without_hit_offers_nothing(client: httpx.Client) -> None:
    html = client.get("/aussteller-suche", params={"issuer_text": "Neue Firma"}).text
    assert "<button" not in html


def test_search_endpoint_shows_the_choice_as_hidden_field(client: httpx.Client) -> None:
    bank = add_issuer(client)
    html = client.get(
        "/aussteller-suche",
        params={"issuer_text": "Beispielbank", "issuer_choice": f"id:{bank.id}"},
    ).text
    assert f'name="issuer_choice" value="id:{bank.id}"' in html
    assert 'data-name="Beispielbank AG"' in html and "treffer" not in html and "ändern" not in html
    alias = client.get(
        "/aussteller-suche",
        params={"issuer_text": "Beispielbank Filiale", "issuer_choice": f"alias:{bank.id}"},
    ).text
    assert "Neuer Alias: „Beispielbank Filiale“ zu Beispielbank AG" in alias
    assert f'value="alias:{bank.id}"' in alias


def test_field_has_private_checkbox_in_the_line_of_the_input(client: httpx.Client) -> None:
    document = taken_in(client)
    html = client.get(document.url).text
    line = html.split('class="zeile"')[1].split("</div>")[0]
    assert 'name="issuer_text"' in line and 'name="issuer_private"' in line


def test_search_endpoint_exact_name_offers_no_alias(client: httpx.Client) -> None:
    add_issuer(client, "Beispielbank AG")
    html = client.get("/aussteller-suche", params={"issuer_text": "beispielbank ag"}).text
    assert "Neuer Alias" not in html


def test_search_prefills_last_issuer_for_the_kind(client: httpx.Client) -> None:
    bank = add_issuer(client)
    assert take(client, issuer_choice=f"id:{bank.id}").status_code == 303
    html = client.get("/aussteller-suche", params={"kind": "transfer_protocol"}).text
    assert f'name="issuer_choice" value="id:{bank.id}"' in html
    other = client.get("/aussteller-suche", params={"kind": "andere_art"}).text
    assert "issuer_choice" not in other
    cleared = client.get("/aussteller-suche", params={"kind": "transfer_protocol", "clear": "1"})
    assert 'name="issuer_choice"' not in cleared.text
    assert last_issuer(state_of(client), "anna", "transfer_protocol") == bank
    assert last_issuer(state_of(client), "anna", "andere_art") is None


# --- Aufnehmen ---------------------------------------------------------------------------------


def test_take_in_with_existing_issuer(client: httpx.Client) -> None:
    bank = add_issuer(client)
    assert take(client, issuer_choice=f"id:{bank.id}").status_code == 303
    assert only_document(client).issuer == bank.address


def test_take_in_without_issuer_stays_possible(client: httpx.Client) -> None:
    assert take(client).status_code == 303
    assert only_document(client).issuer is None
    assert issuers(client) == []


def test_take_in_creates_issuer_and_document_together(client: httpx.Client) -> None:
    response = take(client, issuer_choice="new", issuer_text=" Beispiel GmbH ", issuer_private="1")
    assert response.status_code == 303
    [created] = issuers(client)
    assert created.name == "Beispiel GmbH"
    assert created.private_person
    assert only_document(client).issuer == created.address


def test_take_in_new_issuer_is_not_private_by_default(client: httpx.Client) -> None:
    take(client, issuer_choice="new", issuer_text="Beispiel GmbH")
    assert not issuers(client)[0].private_person


def test_rejected_take_in_leaves_no_new_issuer(client: httpx.Client) -> None:
    assert take(client).status_code == 303  # die Datei ist danach aufgenommen
    again = take(client, issuer_choice="new", issuer_text="Beispiel GmbH")
    assert again.status_code == 409  # nicht mehr offen
    assert issuers(client) == []


def test_take_in_rejected_for_year_creates_no_issuer(client: httpx.Client) -> None:
    response = take(client, year="1900", issuer_choice="new", issuer_text="Beispiel GmbH")
    assert response.status_code == 422
    assert issuers(client) == []
    assert state_of(client).of_kind(Document) == []


def test_take_in_adds_alias_to_existing_issuer(client: httpx.Client) -> None:
    bank = add_issuer(client)
    response = take(client, issuer_choice=f"alias:{bank.id}", issuer_text="Beispielbank")
    assert response.status_code == 303
    [changed] = issuers(client)
    assert changed.aliases == ("Beispielbank",)
    assert changed.id == bank.id
    assert only_document(client).issuer == bank.address


def test_text_without_choice_creates_new_issuer(client: httpx.Client) -> None:
    assert take(client, issuer_text=" Irgendwer ", issuer_private="1").status_code == 303
    [created] = issuers(client)
    assert (created.name, created.private_person) == ("Irgendwer", True)
    assert only_document(client).issuer == created.address


def test_text_without_choice_naming_existing_issuer_is_duplicate(client: httpx.Client) -> None:
    add_issuer(client, aliases=("Muster-Sparkasse",))
    response = take(client, issuer_text="muster-SPARKASSE")
    assert response.status_code == 422
    assert "Duplikat zu: Beispielbank AG" in response.text
    assert 'value="muster-SPARKASSE"' in response.text
    assert len(issuers(client)) == 1
    assert state_of(client).of_kind(Document) == []


def test_vanished_issuer_is_rejected(client: httpx.Client) -> None:
    response = take(client, issuer_choice="id:ZZZZZZZZZZ")
    assert response.status_code == 422
    assert "nicht mehr da" in response.text


def test_new_with_existing_name_is_rejected(client: httpx.Client) -> None:
    add_issuer(client)
    response = take(client, issuer_choice="new", issuer_text="beispielbank ag")
    assert response.status_code == 422
    assert len(issuers(client)) == 1


def test_take_in_post_needs_origin(client: httpx.Client) -> None:
    data = {"sha256": SHA, "kind": "transfer_protocol", "year": "2025"}
    assert client.post("/belege/aufnehmen", data=data).status_code == 403


def test_resolve_issuer_without_input_is_no_issuer() -> None:
    assert resolve_issuer(State({}), {}) == IssuerChoice()
    assert resolve_issuer(State({}), {"issuer_text": "  "}) == IssuerChoice()


def test_resolve_issuer_empty_choice_with_text_creates_new() -> None:
    result = resolve_issuer(State({}), {"issuer_text": " Beispiel GmbH ", "issuer_private": "1"})
    assert isinstance(result, IssuerChoice)
    [put] = result.changes
    assert isinstance(put, Put) and isinstance(put.entry, Issuer)
    assert (put.entry.name, put.entry.private_person) == ("Beispiel GmbH", True)
    assert result.address == put.entry.address


# --- Ablage zeigt den Aussteller ---------------------------------------------------------------


def test_ablage_row_shows_issuer_of_taken_in_file(client: httpx.Client) -> None:
    take(client, issuer_choice="new", issuer_text="Beispiel GmbH")
    html = client.get("/belege?stand=aufgenommen").text
    assert '<span class="aussteller">Beispiel GmbH</span>' in html


# --- Ändern am Dokument ------------------------------------------------------------------------


def taken_in(client: httpx.Client) -> Document:
    assert take(client).status_code == 303
    return only_document(client)


def change(client: httpx.Client, document: Document, **fields: str) -> httpx.Response:
    return client.post(f"/dokumente/{document.id}/aendern", data=fields, headers=ORIGIN)


def test_document_page_shows_field_and_get_writes_nothing(client: httpx.Client) -> None:
    document = taken_in(client)
    before = state_of(client)
    html = client.get(document.url).text
    assert "Kein Aussteller angegeben." in html
    assert 'hx-get="/aussteller-suche"' in html
    assert state_of(client) == before


def test_change_issuer_on_document(client: httpx.Client) -> None:
    document = taken_in(client)
    bank = add_issuer(client)
    response = change(client, document, issuer_choice=f"id:{bank.id}")
    assert response.status_code == 303
    assert only_document(client).issuer == bank.address
    assert bank.name in client.get(document.url).text


def test_change_issuer_creates_new_one_and_can_remove(client: httpx.Client) -> None:
    document = taken_in(client)
    assert (
        change(client, document, issuer_choice="new", issuer_text="Beispiel GmbH").status_code
        == 303
    )
    [created] = issuers(client)
    assert only_document(client).issuer == created.address
    assert change(client, document, issuer_choice="").status_code == 303
    assert only_document(client).issuer is None
    assert issuers(client) == [created]


def test_change_issuer_adds_alias(client: httpx.Client) -> None:
    document = taken_in(client)
    bank = add_issuer(client)
    change(client, document, issuer_choice=f"alias:{bank.id}", issuer_text="Beispielbank")
    assert issuers(client)[0].aliases == ("Beispielbank",)
    assert only_document(client).issuer == bank.address


def test_change_issuer_rejection_keeps_state(client: httpx.Client) -> None:
    document = taken_in(client)
    add_issuer(client)
    before = state_of(client)
    response = change(client, document, issuer_text="beispielbank AG")
    assert response.status_code == 422
    assert state_of(client) == before


def test_new_and_alias_name_the_issuer_that_already_has_the_name(client: httpx.Client) -> None:
    bank = add_issuer(client, aliases=("Muster-Sparkasse",))
    werke = add_issuer(client, "Stadtwerke Beispielstadt")
    state = state_of(client)
    new = resolve_issuer(state, {"issuer_choice": "new", "issuer_text": " muster-sparkasse "})
    assert new == "Duplikat zu: Beispielbank AG. Bitte aus der Suche wählen."
    alias = resolve_issuer(
        state, {"issuer_choice": f"alias:{werke.id}", "issuer_text": "BEISPIELBANK ag"}
    )
    assert isinstance(alias, str) and "Duplikat zu: Beispielbank AG" in alias
    own = resolve_issuer(
        state, {"issuer_choice": f"alias:{bank.id}", "issuer_text": "beispielbank ag"}
    )
    assert own == IssuerChoice(bank.address)


def test_change_issuer_needs_origin_and_known_document(client: httpx.Client) -> None:
    document = taken_in(client)
    assert client.post(f"/dokumente/{document.id}/aendern", data={}).status_code == 403
    assert change(client, document.model_copy(update={"id": "ZZZZZZZZZZ"})).status_code == 404
