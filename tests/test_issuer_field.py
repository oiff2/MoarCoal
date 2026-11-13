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


def test_search_endpoint_offers_hit_new_and_alias_and_writes_nothing(client: httpx.Client) -> None:
    add_issuer(client, "Beispielbank AG")
    before = state_of(client)
    html = client.get("/aussteller-suche", params={"issuer_text": "beispielbank ag filiale"}).text
    assert "Beispielbank AG" in html
    assert "Neu anlegen: „beispielbank ag filiale“" in html
    assert "Privatperson" in html
    assert "Als weiteren Namen zu Beispielbank AG hinzufügen" in html
    assert state_of(client) == before


def test_search_endpoint_without_hit_offers_only_new(client: httpx.Client) -> None:
    html = client.get("/aussteller-suche", params={"issuer_text": "Neue Firma"}).text
    assert "Neu anlegen: „Neue Firma“" in html
    assert "Als weiteren Namen" not in html


def test_search_endpoint_exact_name_offers_no_new(client: httpx.Client) -> None:
    add_issuer(client, "Beispielbank AG")
    html = client.get("/aussteller-suche", params={"issuer_text": "beispielbank ag"}).text
    assert "Neu anlegen" not in html


def test_search_prefills_last_issuer_for_the_kind(client: httpx.Client) -> None:
    bank = add_issuer(client)
    assert take(client, issuer_choice=f"id:{bank.id}").status_code == 303
    html = client.get("/aussteller-suche", params={"kind": "transfer_protocol"}).text
    assert f'value="id:{bank.id}" checked' in html
    other = client.get("/aussteller-suche", params={"kind": "andere_art"}).text
    assert "checked" in other and "id:" not in other
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
    assert again.status_code == 409  # nicht mehr im Eingang
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


def test_unclear_issuer_input_is_rejected_and_keeps_text(client: httpx.Client) -> None:
    response = take(client, issuer_text="Irgendwer")  # Text, aber keine Auswahl
    assert response.status_code == 422
    assert "Bitte einen Aussteller aus der Suche wählen." in response.text
    assert 'value="Irgendwer"' in response.text
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
    return client.post(f"/dokumente/{document.id}/aussteller", data=fields, headers=ORIGIN)


def test_document_page_shows_field_and_get_writes_nothing(client: httpx.Client) -> None:
    document = taken_in(client)
    before = state_of(client)
    html = client.get(f"/dokumente/{document.id}").text
    assert "Kein Aussteller angegeben." in html
    assert 'hx-get="/aussteller-suche"' in html
    assert state_of(client) == before


def test_change_issuer_on_document(client: httpx.Client) -> None:
    document = taken_in(client)
    bank = add_issuer(client)
    response = change(client, document, issuer_choice=f"id:{bank.id}")
    assert response.status_code == 303
    assert only_document(client).issuer == bank.address
    assert bank.name in client.get(f"/dokumente/{document.id}").text


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
    before = state_of(client)
    response = change(client, document, issuer_text="Irgendwer")
    assert response.status_code == 422
    assert state_of(client) == before


def test_new_and_alias_name_the_issuer_that_already_has_the_name(client: httpx.Client) -> None:
    bank = add_issuer(client, aliases=("Muster-Sparkasse",))
    werke = add_issuer(client, "Stadtwerke Beispielstadt")
    state = state_of(client)
    new = resolve_issuer(state, {"issuer_choice": "new", "issuer_text": " muster-sparkasse "})
    assert new == "Der Name gehört schon zu „Beispielbank AG“; bitte aus der Suche wählen."
    alias = resolve_issuer(
        state, {"issuer_choice": f"alias:{werke.id}", "issuer_text": "BEISPIELBANK ag"}
    )
    assert isinstance(alias, str) and "„Beispielbank AG“" in alias
    own = resolve_issuer(
        state, {"issuer_choice": f"alias:{bank.id}", "issuer_text": "beispielbank ag"}
    )
    assert own == IssuerChoice(bank.address)


def test_change_issuer_needs_origin_and_known_document(client: httpx.Client) -> None:
    document = taken_in(client)
    assert client.post(f"/dokumente/{document.id}/aussteller", data={}).status_code == 403
    assert change(client, document.model_copy(update={"id": "ZZZZZZZZZZ"})).status_code == 404
