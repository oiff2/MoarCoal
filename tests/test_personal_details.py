"""Angaben zur Person: Baustein, Nutzer anlegen, Umleitung, Aussteller, Sperrliste (tmp_path)."""

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient
from pydantic import ValidationError

from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.personal_details import (
    PersonalDetailsInvalid,
    details_for_issuer,
    details_of,
    personal_details_changes,
)
from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Delete,
    EntryAddress,
    Issuer,
    Merge,
    PersonalDetails,
    Put,
    Rejected,
    State,
    Store,
    denylist_lines,
    entry_checksum,
    open_store,
)

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
USER = "anna"
PERSON = {"first_name": "Erika", "last_name": "Musterfrau"}


def details(
    owner: str = USER,
    last_name: str = "Musterfrau",
    issuer: EntryAddress | None = None,
) -> PersonalDetails:
    return PersonalDetails(owner=owner, first_name="Erika", last_name=last_name, issuer=issuer)


def make_client(root: Path, with_user: bool = False) -> httpx.Client:
    # `with_user` kennt `make_app` aus app_helper.py
    options: dict[str, Any] = {"with_user": with_user}
    app = make_app(PORT, root, modules=[WORK], user=USER, **options)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def created(root: Path) -> httpx.Client:
    client = make_client(root)
    assert client.post("/person", data=PERSON, headers=ORIGIN).status_code == 303
    return client


def state_of(root: Path) -> State:
    return open_store(root, WORK.kinds).state()


def only_issuer(root: Path) -> Issuer:
    (found,) = state_of(root).of_kind(Issuer)
    return found


def checksum_of(client: httpx.Client) -> str:
    match = re.search(r'name="checksum" value="([0-9a-f]+)"', client.get("/person").text)
    assert match
    return match.group(1)


# --- Baustein ---------------------------------------------------------------------------------


def test_names_are_required() -> None:
    with pytest.raises(ValidationError):
        PersonalDetails(owner=USER, first_name="", last_name="Musterfrau")
    with pytest.raises(ValidationError):
        PersonalDetails(owner=USER, first_name="Erika", last_name="  ")


def test_display_name_is_first_and_last_name() -> None:
    assert details().display_name == "Erika Musterfrau"


def test_only_one_per_user(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    assert isinstance(store.apply([Put(details())]), Applied)
    second = store.apply([Put(details(last_name="Zwei"))])
    assert isinstance(second, Rejected)
    assert "gibt es schon" in " ".join(second.reasons.values())
    other = store.apply([Put(details("berta"))])
    assert isinstance(other, Applied)


def test_issuer_must_exist(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    ghost = EntryAddress(kind="Issuer", id="A" * 10)
    result = store.apply([Put(details(issuer=ghost))])
    assert isinstance(result, Rejected)


def test_details_are_stored_per_user(tmp_path: Path) -> None:
    open_store(tmp_path, []).apply([Put(details())])
    assert (tmp_path / "users" / USER / "personal_details.json").exists()


# --- reiner Kern --------------------------------------------------------------------------------


def test_changes_reject_missing_names() -> None:
    with pytest.raises(PersonalDetailsInvalid) as error:
        personal_details_changes(State({}), USER, " ", "")
    assert len(error.value.problems) == 2


def test_unresolvable_reference_creates_the_issuer_anew() -> None:
    ghost = EntryAddress(kind="Issuer", id="A" * 10)
    known = details(issuer=ghost)
    state = State({e.address: e for e in [known]})
    changes = personal_details_changes(state, USER, "Erika", "Neu", "x")
    issuers = [c.entry for c in changes if isinstance(c, Put) and isinstance(c.entry, Issuer)]
    (issuer,) = issuers
    assert (issuer.name, issuer.private_person, issuer.owner) == (
        "Erika Neu",
        True,
        COMMON_OWNER,
    )
    assert details_for_issuer(State({e.address: e for e in [issuer]}), issuer) is None


# --- Nutzer anlegen, Startseite, Umleitung --------------------------------------------------------


def test_without_user_the_start_page_shows_the_form_only(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/").text
    assert "Bitte Nutzer anlegen" in page
    assert 'name="first_name"' in page and 'name="last_name"' in page
    assert "Nutzer anlegen</button>" in page
    assert ">MoarCoal</a>" in page
    for link in ("/belege", "/aussteller", "/befunde", "/arbeit", "/steuerjahr"):
        assert f'href="{link}' not in page


def test_without_user_other_pages_redirect_to_the_start_page(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    for path in ("/belege", "/aussteller", "/befunde", "/arbeit", "/belege/dokumente"):
        response = client.get(path)
        assert (response.status_code, response.headers["location"]) == (303, "/"), path
    posted = client.post("/aussteller/ABCDEFGHIJ", data={}, headers=ORIGIN)
    assert (posted.status_code, posted.headers["location"]) == (303, "/")
    assert client.get("/person").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_creating_the_user_shows_the_modules(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/person", data=PERSON, headers=ORIGIN)
    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert client.get("/belege").status_code == 200
    page = client.get("/").text
    assert 'href="/belege' in page and "Bitte Nutzer anlegen" not in page
    assert '<a href="/person">Erika Musterfrau</a>' in page


def test_missing_name_is_not_stored(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/person", data={"first_name": "Erika", "last_name": ""}, headers=ORIGIN)
    assert response.status_code == 422
    assert "Name: darf nicht leer sein" in response.text
    assert 'value="Erika"' in response.text
    assert details_of(state_of(tmp_path), USER) is None
    assert client.get("/belege").status_code == 303


# --- Aussteller des Nutzers -----------------------------------------------------------------------


def test_saving_creates_details_and_the_private_issuer_in_one_go(tmp_path: Path) -> None:
    created(tmp_path)
    state = state_of(tmp_path)
    details = details_of(state, USER)
    issuer = only_issuer(tmp_path)
    assert details is not None and details.issuer == issuer.address
    assert (issuer.name, issuer.private_person, issuer.owner) == (
        "Erika Musterfrau",
        True,
        COMMON_OWNER,
    )
    assert details_for_issuer(state, issuer) == details


def test_changing_the_name_keeps_the_issuer_and_keeps_the_old_name_as_alias(
    tmp_path: Path,
) -> None:
    client = created(tmp_path)
    before = only_issuer(tmp_path)
    response = client.post(
        "/person",
        data={"first_name": "Erika", "last_name": "Neumann", "checksum": checksum_of(client)},
        headers=ORIGIN,
    )
    assert (response.status_code, response.headers["location"]) == (303, "/person")
    after = only_issuer(tmp_path)
    assert after.id == before.id
    assert (after.name, after.aliases) == ("Erika Neumann", ("Erika Musterfrau",))
    assert "Erika Neumann" in client.get("/person").text
    assert "Erika Neumann" in client.get("/").text
    # zurück zum alten Namen: er ist kein Alias mehr, der neue wird einer
    client.post(
        "/person",
        data={**PERSON, "checksum": checksum_of(client)},
        headers=ORIGIN,
    )
    assert (only_issuer(tmp_path).name, only_issuer(tmp_path).aliases) == (
        "Erika Musterfrau",
        ("Erika Neumann",),
    )


def test_a_stale_form_is_rejected(tmp_path: Path) -> None:
    client = created(tmp_path)
    response = client.post(
        "/person", data={**PERSON, "first_name": "Berta", "checksum": "0" * 64}, headers=ORIGIN
    )
    assert response.status_code == 409
    details = details_of(state_of(tmp_path), USER)
    assert details is not None and details.first_name == "Erika"
    assert only_issuer(tmp_path).name == "Erika Musterfrau"


def test_an_issuer_with_the_same_name_is_taken_over_and_marked_private(tmp_path: Path) -> None:
    open_store(tmp_path, []).apply(
        [Put(Issuer(owner=COMMON_OWNER, name="Beispiel GmbH", aliases=("Erika Musterfrau",)))]
    )
    existing = only_issuer(tmp_path)
    created(tmp_path)
    taken = only_issuer(tmp_path)  # genau einer, kein zweiter
    assert taken.id == existing.id and taken.private_person
    assert taken.name == "Erika Musterfrau" and taken.aliases == ("Beispiel GmbH",)
    details = details_of(state_of(tmp_path), USER)
    assert details is not None and details.issuer == taken.address


def test_a_name_held_by_another_issuer_is_rejected(tmp_path: Path) -> None:
    client = created(tmp_path)
    open_store(tmp_path, []).apply([Put(Issuer(owner=COMMON_OWNER, name="Hans Beispiel"))])
    response = client.post(
        "/person",
        data={"first_name": "Hans", "last_name": "Beispiel", "checksum": checksum_of(client)},
        headers=ORIGIN,
    )
    assert response.status_code == 409
    details = details_of(state_of(tmp_path), USER)
    assert details is not None and details.first_name == "Erika"  # nichts halb geschrieben


def test_a_merged_own_issuer_is_resolved_not_created_anew(tmp_path: Path) -> None:
    client = created(tmp_path)
    store = open_store(tmp_path, [])
    own = only_issuer(tmp_path)
    other = Issuer(owner=COMMON_OWNER, name="E. Musterfrau")
    store.apply([Put(other)])
    result = store.apply(
        [Merge(own.address, other.address, entry_checksum(own), entry_checksum(other))]
    )
    assert isinstance(result, Applied)
    client = make_client(tmp_path)  # lädt den neuen Stand
    client.post(
        "/person",
        data={"first_name": "Erika", "last_name": "Neumann", "checksum": checksum_of(client)},
        headers=ORIGIN,
    )
    (issuer,) = state_of(tmp_path).of_kind(Issuer)
    assert issuer.id == other.id and issuer.name == "Erika Neumann"
    assert {"Erika Musterfrau", "E. Musterfrau"} <= set(issuer.aliases)


# --- Sperrliste -------------------------------------------------------------------------------


def test_the_name_reaches_the_denylist_only_through_the_issuer(tmp_path: Path) -> None:
    created(tmp_path)
    state = state_of(tmp_path)
    assert denylist_lines(state.of_kind(Issuer)) == ["Erika Musterfrau", "Musterfrau"]
    derived = (tmp_path / "common" / "derived-denylist.txt").read_text(encoding="utf-8")
    assert derived.splitlines() == ["Erika Musterfrau", "Musterfrau"]
    assert "Erika" not in derived.splitlines()  # kurze Teile allein sind nicht gesperrt
    assert not hasattr(PersonalDetails, "sensitive_values")


def test_the_old_name_stays_in_the_denylist(tmp_path: Path) -> None:
    client = created(tmp_path)
    client.post(
        "/person",
        data={"first_name": "Erika", "last_name": "Neumann", "checksum": checksum_of(client)},
        headers=ORIGIN,
    )
    lines = denylist_lines(state_of(tmp_path).of_kind(Issuer))
    assert {"Erika Musterfrau", "Musterfrau", "Erika Neumann", "Neumann"} <= set(lines)


# --- Sperre auf /aussteller -----------------------------------------------------------------------


def test_the_own_issuer_is_read_only_on_the_issuer_page(tmp_path: Path) -> None:
    client = created(tmp_path)
    issuer = only_issuer(tmp_path)
    page = client.get(f"/aussteller/{issuer.id}").text
    assert 'name="name"' not in page and 'name="private_person"' not in page
    assert 'href="/person"' in page and "Angaben zur Person" in page
    assert "/loeschen" not in page
    assert 'name="aliases"' in page


def test_name_and_private_person_cannot_be_changed_but_aliases_can(tmp_path: Path) -> None:
    client = created(tmp_path)
    issuer = only_issuer(tmp_path)
    response = client.post(
        f"/aussteller/{issuer.id}",
        data={
            "name": "Hacker",
            "aliases": "Erika M.",
            "checksum": entry_checksum(issuer),
        },
        headers=ORIGIN,
    )
    assert response.status_code == 303
    after = only_issuer(tmp_path)
    assert (after.name, after.private_person, after.aliases) == (
        "Erika Musterfrau",
        True,
        ("Erika M.",),
    )


def test_the_own_issuer_cannot_be_deleted(tmp_path: Path) -> None:
    client = created(tmp_path)
    issuer = only_issuer(tmp_path)
    response = client.post(
        f"/aussteller/{issuer.id}/loeschen",
        data={"checksum": entry_checksum(issuer)},
        headers=ORIGIN,
    )
    assert response.status_code == 409
    assert only_issuer(tmp_path).id == issuer.id
    store: Store = open_store(tmp_path, [])  # auch der Schreibweg selbst sperrt
    refused = store.apply([Delete(issuer.address, entry_checksum(issuer))])
    assert isinstance(refused, Rejected)


def test_an_ordinary_issuer_stays_editable(tmp_path: Path) -> None:
    client = created(tmp_path)
    other = Issuer(owner=COMMON_OWNER, name="Beispielbank AG")
    open_store(tmp_path, []).apply([Put(other)])
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{other.id}").text
    assert 'name="name"' in page and "/loeschen" in page
