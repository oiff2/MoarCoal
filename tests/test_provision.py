"""Tests des Moduls Vorsorge: Steuerliche Bedeutung, laufende Verträge, Seite (nur tmp_path)."""

import datetime
import re
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient
from pydantic import ValidationError

from moarcoal.modules import MODULES
from moarcoal.modules.provision import REGISTRATION, AgreementMeaning, TaxMeaning
from moarcoal.modules.provision.meaning import (
    MeaningInvalid,
    meaning_changes,
    meaning_of,
    parse_meaning,
    runs_in,
)
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Delete,
    EntryAddress,
    Issuer,
    Put,
    Rejected,
    Store,
    entry_checksum,
)
from moarcoal.web.links import agreements_url

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


def make_client(root: Path) -> tuple[httpx.Client, Store]:
    app = make_app(PORT, root, user="anna")
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    return client, app.state.store


def add_agreement(
    store: Store, name: str = "Haftpflicht", owner: str = "anna", **fields: object
) -> Agreement:
    partner = Issuer(owner=COMMON_OWNER, name=f"Beispielversicherung {name}")
    agreement = Agreement(owner=owner, issuer=partner.address, name=name, **fields)  # pyright: ignore[reportArgumentType]
    assert isinstance(store.apply([Put(partner), Put(agreement)]), Applied)
    return agreement


def own_state(store: Store, user: str = "anna") -> ModuleState:
    return ModuleState(store.state(), REGISTRATION, user)


def meanings(store: Store) -> list[AgreementMeaning]:
    return own_state(store).all(AgreementMeaning)


def set_meaning(
    store: Store, agreement: Agreement, meaning: TaxMeaning | None, seen: str = ""
) -> Applied | Rejected:
    return store.apply(meaning_changes(own_state(store), agreement, meaning, seen))


def post(
    client: httpx.Client, agreement: Agreement, meaning: str, checksum: str = "", year: int = 2025
):
    data = {"meaning": meaning, "checksum": checksum, "year": str(year)}
    return client.post(f"/vorsorge/bedeutung/{agreement.id}", data=data, headers=ORIGIN)


# --- im Jahr laufende Verträge ----------------------------------------------------------------


def test_an_agreement_without_start_and_end_runs_in_every_year() -> None:
    partner = Issuer(owner=COMMON_OWNER, name="Beispiel AG")
    agreement = Agreement(owner="anna", issuer=partner.address, name="Hausrat")
    assert runs_in(agreement, 1999) and runs_in(agreement, 2025)


def test_the_term_has_to_touch_the_year() -> None:
    partner = Issuer(owner=COMMON_OWNER, name="Beispiel AG")

    def agreement(start: datetime.date | None, end: datetime.date | None) -> Agreement:
        return Agreement(owner="anna", issuer=partner.address, name="Hausrat", start=start, end=end)

    jan_first, dec_31 = datetime.date(2025, 1, 1), datetime.date(2025, 12, 31)
    assert runs_in(agreement(dec_31, None), 2025)  # beginnt am letzten Tag
    assert not runs_in(agreement(datetime.date(2026, 1, 1), None), 2025)
    assert runs_in(agreement(None, jan_first), 2025)  # endet am ersten Tag
    assert not runs_in(agreement(None, datetime.date(2024, 12, 31)), 2025)
    assert runs_in(agreement(datetime.date(2020, 6, 1), datetime.date(2030, 6, 1)), 2025)
    assert runs_in(agreement(datetime.date(2025, 3, 1), datetime.date(2025, 4, 1)), 2025)


# --- Bedeutung setzen, ändern, entfernen -----------------------------------------------------


def test_set_change_and_remove_a_meaning(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(set_meaning(store, agreement, TaxMeaning.BASIC_PENSION), Applied)
    found = meaning_of(own_state(store), agreement)
    assert found is not None and found.meaning is TaxMeaning.BASIC_PENSION
    assert isinstance(
        set_meaning(store, agreement, TaxMeaning.DISABILITY, entry_checksum(found)), Applied
    )
    changed = meaning_of(own_state(store), agreement)
    assert changed is not None and changed.meaning is TaxMeaning.DISABILITY
    assert changed.id == found.id  # geändert, nicht neu angelegt
    assert isinstance(set_meaning(store, agreement, None, entry_checksum(changed)), Applied)
    assert meanings(store) == []


def test_removing_a_meaning_that_is_not_there_changes_nothing(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert meaning_changes(own_state(store), agreement, None, "") == []


def test_a_stale_form_is_rejected(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(set_meaning(store, agreement, TaxMeaning.BASIC_PENSION), Applied)
    # das Formular zeigte noch keine Bedeutung
    assert isinstance(set_meaning(store, agreement, TaxMeaning.DISABILITY, ""), Rejected)
    found = meanings(store)
    assert [m.meaning for m in found] == [TaxMeaning.BASIC_PENSION]


def test_an_agreement_has_at_most_one_meaning(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    first = AgreementMeaning(
        owner="anna", agreement=agreement.address, meaning=TaxMeaning.BASIC_PENSION
    )
    second = AgreementMeaning(
        owner="anna", agreement=agreement.address, meaning=TaxMeaning.UNEMPLOYMENT
    )
    assert isinstance(store.apply([Put(first)]), Applied)
    result = store.apply([Put(second)])
    assert isinstance(result, Rejected)
    assert "schon eine Steuerliche Bedeutung" in " ".join(result.reasons.values())
    assert isinstance(store.apply([Put(first), Put(second)]), Rejected)


def test_only_an_agreement_of_the_user_can_get_a_meaning(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    foreign = add_agreement(store, name="Fremd", owner="berta")
    entry = AgreementMeaning(
        owner="anna", agreement=foreign.address, meaning=TaxMeaning.BASIC_PENSION
    )
    assert isinstance(store.apply([Put(entry)]), Rejected)
    missing = AgreementMeaning(
        owner="anna",
        agreement=foreign.address.model_copy(update={"id": "A" * 10}),
        meaning=TaxMeaning.BASIC_PENSION,
    )
    assert isinstance(store.apply([Put(missing)]), Rejected)


def test_the_meaning_has_to_point_at_an_agreement() -> None:
    with pytest.raises(ValidationError):
        AgreementMeaning(
            owner="anna",
            agreement=EntryAddress(kind="Issuer", id="A" * 10),
            meaning=TaxMeaning.BASIC_PENSION,
        )


def test_deleting_the_agreement_takes_the_meaning_along(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(set_meaning(store, agreement, TaxMeaning.UNEMPLOYMENT), Applied)
    result = store.apply([Delete(agreement.address, expected=entry_checksum(agreement))])
    assert isinstance(result, Applied)
    assert meanings(store) == []


def test_parse_meaning() -> None:
    assert parse_meaning("") is None
    assert parse_meaning(" basic_pension ") is TaxMeaning.BASIC_PENSION
    with pytest.raises(MeaningInvalid):
        parse_meaning("nonsense")


# --- Seite ------------------------------------------------------------------------------------


def test_the_module_is_registered_with_its_key_and_in_the_navigation(tmp_path: Path) -> None:
    assert REGISTRATION in MODULES and REGISTRATION.key == "provision"
    client, _ = make_client(tmp_path)
    page = client.get("/vorsorge").text
    assert 'href="/vorsorge"' in page
    assert client.get("/vorsorge?jahr=2025").status_code == 200


def test_the_page_lists_the_agreements_running_in_the_year(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    add_agreement(store, "Offen")
    add_agreement(store, "Beendet", end=datetime.date(2024, 5, 1))
    add_agreement(store, "Später", start=datetime.date(2026, 1, 2))
    add_agreement(store, "Fremd", owner="berta")
    page = client.get("/vorsorge?jahr=2025").text
    assert "Offen" in page
    assert "Beendet" not in page and "Später" not in page and "Fremd" not in page
    assert "Beendet" in client.get("/vorsorge?jahr=2024").text


def test_setting_a_meaning_on_the_page_and_showing_it(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    agreement = add_agreement(store)
    response = post(client, agreement, "private_health_care")
    assert response.status_code == 303 and response.headers["location"] == "/vorsorge?jahr=2025"
    page = client.get("/vorsorge?jahr=2025").text
    assert re.search(r'<option value="private_health_care" selected>', page)
    found = meanings(store)[0]
    response = post(client, agreement, "", entry_checksum(found))
    assert response.status_code == 303 and meanings(store) == []


def test_a_rejected_input_shows_the_page_with_the_reason(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    agreement = add_agreement(store)
    response = post(client, agreement, "nonsense")
    assert response.status_code == 422 and "eine der angebotenen" in response.text
    assert meanings(store) == []
    assert isinstance(set_meaning(store, agreement, TaxMeaning.BASIC_PENSION), Applied)
    stale = post(client, agreement, "disability", checksum="")
    assert stale.status_code == 409 and "Inzwischen geändert" in stale.text


def test_a_foreign_or_unknown_agreement_is_not_found(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    foreign = add_agreement(store, name="Fremd", owner="berta")
    assert post(client, foreign, "basic_pension").status_code == 404
    assert (
        client.post("/vorsorge/bedeutung/nope", data={"meaning": ""}, headers=ORIGIN).status_code
        == 404
    )
    assert meanings(store) == []


def test_the_empty_page_points_to_the_agreements(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert agreements_url() in client.get("/vorsorge?jahr=2025").text
