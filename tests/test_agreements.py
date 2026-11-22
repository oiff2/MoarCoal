"""Baustein Vertrag: Eintragsart, Schreibweg, Sperrliste, Zuordnen und Seiten (tmp_path)."""

import datetime
import re
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.agreements import (
    AgreementInvalid,
    agreement_changes,
    agreements_of,
    assign,
    documents_of_agreement,
    unassign,
)
from moarcoal.issuer_field import IssuerChoice
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Delete,
    Document,
    Issuer,
    Merge,
    Put,
    Rejected,
    Store,
    entry_checksum,
    open_store,
)
from moarcoal.storage.agreements import CATEGORIES
from moarcoal.web.links import document_url

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
NUMBER = "ZZ-4711-0815"  # erfunden


def issuer(name: str = "Beispielversicherung AG") -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name)


def agreement(partner: Issuer, name: str = "Hausrat", owner: str = "anna", **fields: object):
    return Agreement(owner=owner, issuer=partner.address, name=name, **fields)  # pyright: ignore[reportArgumentType]


def document(owner: str = "anna", sha: str = "b" * 64) -> Document:
    return Document(owner=owner, site="Ablage", path=f"{sha[:4]}.pdf", sha256=sha)


def store_with(root: Path, *entries: object) -> Store:
    store = open_store(root, [])
    assert isinstance(store.apply([Put(e) for e in entries]), Applied)  # pyright: ignore[reportArgumentType]
    return store


# --- Eintragsart und Regeln im Schreibweg -------------------------------------------------------


def test_create_change_and_delete(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(tmp_path, partner)
    contract = agreement(partner, number=NUMBER, category="Versicherung")
    assert isinstance(store.apply([Put(contract)]), Applied)
    assert (tmp_path / "users" / "anna" / "agreements.json").exists()
    changed = contract.model_copy(update={"end": datetime.date(2030, 12, 31)})
    assert isinstance(store.apply([Put(changed, entry_checksum(contract))]), Applied)
    assert isinstance(store.apply([Delete(changed.address, entry_checksum(changed))]), Applied)
    assert store.state().of_kind(Agreement) == []


def test_partner_must_exist_and_be_an_issuer(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    result = store.apply([Put(agreement(issuer()))])
    assert isinstance(result, Rejected)
    assert "Vertragspartner existiert nicht." in result.reasons.values()
    with pytest.raises(ValueError, match="Aussteller"):
        Agreement(owner="anna", issuer=document().address, name="x")


def test_end_before_start_is_invalid() -> None:
    with pytest.raises(ValueError, match="Laufzeit"):
        agreement(issuer(), start=datetime.date(2024, 5, 1), end=datetime.date(2024, 4, 30))
    with pytest.raises(ValueError, match="Bezeichnung"):
        agreement(issuer(), name="  ")


def test_same_partner_and_name_only_once_per_user(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(tmp_path, partner, agreement(partner))
    result = store.apply([Put(agreement(partner, name=" HAUSRAT "))])
    assert isinstance(result, Rejected)
    assert "Diesen Vertrag gibt es schon." in result.reasons.values()
    assert isinstance(store.apply([Put(agreement(partner, owner="berta"))]), Applied)
    assert isinstance(store.apply([Put(agreement(partner, name="Haftpflicht"))]), Applied)


def test_partner_cannot_be_deleted_while_a_contract_names_it(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(tmp_path, partner, agreement(partner))
    result = store.apply([Delete(partner.address, entry_checksum(partner))])
    assert isinstance(result, Rejected)
    assert "Wird noch verwendet." in result.reasons.values()


def test_merging_issuers_moves_the_partner(tmp_path: Path) -> None:
    old, new = issuer("Beispielversicherung"), issuer("Beispielversicherung AG Zweitname")
    contract = agreement(old)
    store = store_with(tmp_path, old, new, contract)
    state = store.state()
    result = store.apply(
        [
            Merge(
                old.address,
                new.address,
                expected=state.checksum(old.address) or "",
                expected_into=state.checksum(new.address) or "",
            )
        ]
    )
    assert isinstance(result, Applied)
    moved = store.state().get(contract.address)
    assert isinstance(moved, Agreement) and moved.issuer == new.address


def test_contract_number_is_in_the_derived_denylist(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(
        tmp_path,
        partner,
        agreement(partner, number=NUMBER),
        agreement(partner, name="Kurz", number="123"),  # unter 6 Zeichen: zu unscharf
        agreement(partner, name="Ohne"),
    )
    lines = (tmp_path / "common" / "derived-denylist.txt").read_text(encoding="utf-8").splitlines()
    assert lines == [NUMBER]
    contract = next(a for a in store.state().of_kind(Agreement) if a.number == NUMBER)
    assert isinstance(store.apply([Delete(contract.address, entry_checksum(contract))]), Applied)
    assert (tmp_path / "common" / "derived-denylist.txt").read_text(encoding="utf-8") == ""


# --- Zuordnen -----------------------------------------------------------------------------------


def test_assign_and_unassign_a_document(tmp_path: Path) -> None:
    partner = issuer()
    contract, letter = agreement(partner), document()
    store = store_with(tmp_path, partner, contract, letter)
    assert isinstance(store.apply([assign(letter, contract.address)]), Applied)
    state = store.state()
    assigned = state.get(letter.address)
    assert isinstance(assigned, Document) and assigned.assignments == (contract.address,)
    assert documents_of_agreement(state, contract) == [assigned]
    assert isinstance(store.apply([assign(assigned, contract.address)]), Applied)  # zweimal: einmal
    again = store.state().get(letter.address)
    assert isinstance(again, Document) and again.assignments == (contract.address,)
    assert isinstance(store.apply([unassign(assigned, contract.address)]), Applied)
    assert documents_of_agreement(store.state(), contract) == []


def test_contract_with_documents_cannot_be_deleted_until_released(tmp_path: Path) -> None:
    partner = issuer()
    contract, letter = agreement(partner), document()
    store = store_with(tmp_path, partner, contract, letter)
    store.apply([assign(letter, contract.address)])
    blocked = store.apply([Delete(contract.address, entry_checksum(contract))])
    assert isinstance(blocked, Rejected)
    assert "Wird noch verwendet." in blocked.reasons.values()
    assigned = store.state().get(letter.address)
    assert isinstance(assigned, Document)
    store.apply([unassign(assigned, contract.address)])
    assert isinstance(store.apply([Delete(contract.address, entry_checksum(contract))]), Applied)


def test_assignment_needs_an_existing_entry_of_the_same_user(tmp_path: Path) -> None:
    partner = issuer()
    foreign = agreement(partner, owner="berta")
    ghost = agreement(partner, name="Gespenst")
    letter = document()
    store = store_with(tmp_path, partner, foreign, letter)
    for target in (foreign, ghost):
        result = store.apply([assign(letter, target.address)])
        assert isinstance(result, Rejected)
        assert "Zuordnung existiert nicht." in result.reasons.values()
    with pytest.raises(ValueError, match="doppelt"):
        letter.model_copy(
            update={"assignments": (foreign.address, foreign.address)}
        ).model_validate({**letter.model_dump(), "assignments": [foreign.address, foreign.address]})


def test_documents_without_assignments_load_unchanged(tmp_path: Path) -> None:
    store_with(tmp_path, document())
    path = tmp_path / "users" / "anna" / "documents.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"assignments": [],', ""))
    loaded = open_store(tmp_path, []).state().of_kind(Document)
    assert [d.assignments for d in loaded] == [()]


# --- Kern ---------------------------------------------------------------------------------------


def test_changes_for_a_contract_carry_the_partner_changes() -> None:
    partner = issuer()
    new = issuer("Neue Versicherung")
    fields = {
        "name": " Leben ",
        "number": NUMBER,
        "category": "Versicherung",
        "start": "2020-01-15",
    }
    changes = agreement_changes(
        "anna", "ABCDEFGHIJ", IssuerChoice(new.address, (Put(new),)), fields
    )
    assert [type(c.entry).__name__ for c in changes if isinstance(c, Put)] == [
        "Issuer",
        "Agreement",
    ]
    last = changes[-1]
    assert isinstance(last, Put)
    contract = last.entry
    assert isinstance(contract, Agreement)
    assert (contract.name, contract.start, contract.end) == (
        "Leben",
        datetime.date(2020, 1, 15),
        None,
    )
    assert partner.address != contract.issuer


def test_changes_report_every_problem() -> None:
    fields = {"name": "", "start": "2020-02-30", "end": "morgen", "category": "x" * 100}
    with pytest.raises(AgreementInvalid) as error:
        agreement_changes("anna", "ABCDEFGHIJ", IssuerChoice(), fields)
    assert len(error.value.problems) == 5
    fields = {"name": "Leben", "start": "2020-05-01", "end": "2020-04-01"}
    with pytest.raises(AgreementInvalid, match="nicht vor dem Beginn"):
        agreement_changes("anna", "ABCDEFGHIJ", IssuerChoice(issuer().address), fields)


def test_agreements_of_lists_only_the_users_sorted(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(
        tmp_path,
        partner,
        agreement(partner, name="zeta"),
        agreement(partner, name="Alpha"),
        agreement(partner, name="Fremd", owner="berta"),
    )
    assert [a.name for a in agreements_of(store.state(), "anna")] == ["Alpha", "zeta"]


# --- Seiten -------------------------------------------------------------------------------------


def make_client(root: Path, user: str = "anna") -> httpx.Client:
    app = make_app(PORT, root, modules=[WORK, TAX_YEAR], user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def checksum_of(page: str) -> str:
    found = re.search(r'name="checksum" value="([0-9a-f]+)"', page)
    assert found
    return found.group(1)


def stored(root: Path) -> list[Agreement]:
    return open_store(root, []).state().of_kind(Agreement)


def test_list_page_and_sidebar(tmp_path: Path) -> None:
    partner = issuer()
    letter = document()
    contract = agreement(partner, category="Versicherung")
    store = store_with(tmp_path, partner, contract, letter)
    store.apply([assign(letter, contract.address)])
    page = make_client(tmp_path).get("/vertraege")
    assert page.status_code == 200
    assert f'href="/vertraege/{contract.id}"' in page.text
    assert f'href="/aussteller/{partner.id}"' in page.text
    assert "Hausrat" in page.text and "Versicherung" in page.text and "unbekannt" in page.text
    assert 'href="/vertraege"' in page.text  # Seitenleiste
    assert make_client(tmp_path, "berta").get("/vertraege").text.count("Hausrat") == 0


def test_create_via_page_with_a_new_partner(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/vertraege",
        data={
            "issuer_text": "Neue Stadtwerke",
            "name": "Strom",
            "number": NUMBER,
            "category": "Sonstiges",
            "start": "2022-03-01",
            "end": "",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 303
    (contract,) = stored(tmp_path)
    assert response.headers["location"] == f"/vertraege/{contract.id}"
    assert (contract.name, contract.number, contract.owner) == ("Strom", NUMBER, "anna")
    assert contract.start == datetime.date(2022, 3, 1) and contract.end is None
    partner = open_store(tmp_path, []).state().get(contract.issuer)
    assert isinstance(partner, Issuer) and partner.name == "Neue Stadtwerke"
    assert NUMBER in (tmp_path / "common" / "derived-denylist.txt").read_text(encoding="utf-8")


def test_create_with_missing_partner_or_bad_dates_shows_hints(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/vertraege", data={"name": "Strom", "start": "gestern"}, headers=ORIGIN)
    assert response.status_code == 422
    assert "Vertragspartner: einen Aussteller" in response.text
    assert "Beginn: Datum als JJJJ-MM-TT" in response.text
    assert 'value="Strom"' in response.text  # Eingabe bleibt stehen
    assert stored(tmp_path) == []


def test_create_duplicate_is_rejected_with_the_reason(tmp_path: Path) -> None:
    partner = issuer()
    store_with(tmp_path, partner, agreement(partner))
    response = make_client(tmp_path).post(
        "/vertraege",
        data={"issuer_choice": f"id:{partner.id}", "name": "hausrat", "category": "Depot"},
        headers=ORIGIN,
    )
    assert response.status_code == 409
    assert "Diesen Vertrag gibt es schon." in response.text
    assert len(stored(tmp_path)) == 1


def test_edit_page_prefills_and_saves(tmp_path: Path) -> None:
    partner = issuer()
    contract = agreement(partner, number=NUMBER, start=datetime.date(2020, 1, 1))
    store_with(tmp_path, partner, contract)
    client = make_client(tmp_path)
    page = client.get(f"/vertraege/{contract.id}")
    assert page.status_code == 200
    assert f'value="{NUMBER}"' in page.text and 'value="2020-01-01"' in page.text
    response = client.post(
        f"/vertraege/{contract.id}",
        data={
            "checksum": checksum_of(page.text),
            "issuer_choice": f"id:{partner.id}",
            "name": "Hausrat neu",
            "category": "Konto",
            "number": NUMBER,
            "end": "2031-01-01",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 303
    (changed,) = stored(tmp_path)
    assert changed.category == "Konto"
    assert (changed.name, changed.end, changed.start) == (
        "Hausrat neu",
        datetime.date(2031, 1, 1),
        None,
    )


def test_edit_with_a_stale_checksum_is_rejected(tmp_path: Path) -> None:
    partner = issuer()
    contract = agreement(partner)
    store_with(tmp_path, partner, contract)
    response = make_client(tmp_path).post(
        f"/vertraege/{contract.id}",
        data={
            "checksum": "0" * 64,
            "issuer_choice": f"id:{partner.id}",
            "name": "Anders",
            "category": "Konto",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 409
    assert stored(tmp_path)[0].name == "Hausrat"


def test_foreign_or_unknown_contract_is_404(tmp_path: Path) -> None:
    partner = issuer()
    contract = agreement(partner, owner="berta")
    store_with(tmp_path, partner, contract)
    client = make_client(tmp_path)
    assert client.get(f"/vertraege/{contract.id}").status_code == 404
    assert client.get("/vertraege/NICHTDA").status_code == 404
    assert client.post(f"/vertraege/{contract.id}/loeschen", headers=ORIGIN).status_code == 404


def test_assign_list_and_release_via_pages(tmp_path: Path) -> None:
    partner = issuer()
    contract, letter = agreement(partner), document()
    store_with(tmp_path, partner, contract, letter)
    client = make_client(tmp_path)
    page = client.get(f"/vertraege/{contract.id}").text
    assert f'<option value="{letter.id}">' in page and "Keine Dokumente zugeordnet." in page
    response = client.post(
        f"/vertraege/{contract.id}/dokumente", data={"document": letter.id}, headers=ORIGIN
    )
    assert response.status_code == 303
    page = client.get(f"/vertraege/{contract.id}").text
    assert f'href="{document_url(letter.id)}"' in page
    assert f'<option value="{letter.id}">' not in page
    assert "/loeschen" in page  # Löschen-Knopf ist immer da
    detail = client.get(document_url(letter.id)).text
    assert f'href="/vertraege/{contract.id}"' in detail  # das Dokument nennt seinen Vertrag
    released = client.post(f"/vertraege/{contract.id}/dokumente/{letter.id}/loesen", headers=ORIGIN)
    assert released.status_code == 303
    page = client.get(f"/vertraege/{contract.id}").text
    assert "Keine Dokumente zugeordnet." in page and "/loeschen" in page
    assert make_client(tmp_path).get(f"/vertraege/{contract.id}").status_code == 200


def test_assigning_a_foreign_document_is_404(tmp_path: Path) -> None:
    partner = issuer()
    contract, foreign = agreement(partner), document(owner="berta")
    store_with(tmp_path, partner, contract, foreign)
    response = make_client(tmp_path).post(
        f"/vertraege/{contract.id}/dokumente", data={"document": foreign.id}, headers=ORIGIN
    )
    assert response.status_code == 404


def test_delete_via_page_and_lock(tmp_path: Path) -> None:
    partner = issuer()
    contract, letter = agreement(partner), document()
    store = store_with(tmp_path, partner, contract, letter)
    store.apply([assign(letter, contract.address)])
    blocked = make_client(tmp_path).post(
        f"/vertraege/{contract.id}/loeschen",
        data={"checksum": entry_checksum(contract)},
        headers=ORIGIN,
    )
    assert blocked.status_code == 409 and "1 Dokument zugeordnet – erst lösen" in blocked.text
    assert len(stored(tmp_path)) == 1
    assigned = store.state().get(letter.address)
    assert isinstance(assigned, Document)
    store.apply([unassign(assigned, contract.address)])
    done = make_client(tmp_path).post(
        f"/vertraege/{contract.id}/loeschen",
        data={"checksum": entry_checksum(contract)},
        headers=ORIGIN,
    )
    assert done.status_code == 303 and done.headers["location"] == "/vertraege"
    assert stored(tmp_path) == []


def test_agreement_link_resolves_for_findings_and_references(tmp_path: Path) -> None:
    from moarcoal.web.helpers import entry_url

    partner = issuer()
    contract = agreement(partner)
    assert entry_url((), contract.address) == f"/vertraege/{contract.id}"


def test_category_only_from_the_fixed_list(tmp_path: Path) -> None:
    partner = issuer()
    store = store_with(tmp_path, partner)
    for category in CATEGORIES:
        entry = agreement(partner, name=f"V {category}", category=category)
        assert isinstance(store.apply([Put(entry)]), Applied)
    result = store.apply([Put(agreement(partner, name="Strom", category="Strom"))])
    assert isinstance(result, Rejected)
    assert any("Art muss eine von" in reason for reason in result.reasons.values())
    page = make_client(tmp_path).get("/vertraege").text
    assert page.count("<option") >= len(CATEGORIES)


def test_same_contract_number_at_the_same_partner_is_rejected(tmp_path: Path) -> None:
    partner, other = issuer(), issuer("Andere Versicherung")
    store = store_with(tmp_path, partner, other, agreement(partner, number="ab-123456"))
    same = store.apply([Put(agreement(partner, name="Zweit", number=" AB-123456 "))])
    assert isinstance(same, Rejected)
    assert any("Vertragsnummer" in reason for reason in same.reasons.values())
    elsewhere = agreement(other, name="Zweit", number="AB-123456")
    assert isinstance(store.apply([Put(elsewhere)]), Applied)  # anderer Vertragspartner
    same_name = agreement(other, name="ZWEIT", number="CD-9")
    assert isinstance(store.apply([Put(same_name)]), Rejected)
    no_number = [agreement(partner, name="Ohne eins"), agreement(partner, name="Ohne zwei")]
    assert isinstance(store.apply([Put(no_number[0])]), Applied)
    assert isinstance(store.apply([Put(no_number[1])]), Applied)  # leere Nummer kollidiert nicht


def test_delete_button_stays_and_the_reason_names_the_documents(tmp_path: Path) -> None:
    partner = issuer()
    contract = agreement(partner)
    letters = [document(sha=c * 64) for c in "bc"]
    store = store_with(tmp_path, partner, contract, *letters)
    for letter in letters:
        assert isinstance(store.apply([assign(letter, contract.address)]), Applied)
    client = make_client(tmp_path)
    assert "/loeschen" in client.get(f"/vertraege/{contract.id}").text
    blocked = client.post(
        f"/vertraege/{contract.id}/loeschen",
        data={"checksum": entry_checksum(contract)},
        headers=ORIGIN,
    )
    assert blocked.status_code == 409
    assert "2 Dokumente zugeordnet – erst lösen" in blocked.text
    assert len(stored(tmp_path)) == 1
