"""Eingaben zur Person im Steuerjahr (#200): Beruf, Telefon, „In dieser Steuererklärung“."""

from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION
from moarcoal.modules.tax_year.entries import YearPersonInput
from moarcoal.modules.tax_year.person_input import (
    in_this_return_choices,
    year_person_input_changes,
)
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Put, Rejected, State, open_store

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
USER = "anna"
CHOICE = in_this_return_choices(ANLAGEN, 2025)[0]
FIELDS = {"occupation": "Beispielberuf", "phone": "+49 (0) 123 4567-89", "in_return": CHOICE}


def client_for(root: Path) -> httpx.Client:
    app = make_app(PORT, root, modules=[REGISTRATION, WORK], user=USER)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def stored(root: Path) -> list[YearPersonInput]:
    return open_store(root, REGISTRATION.kinds).state().of_kind(YearPersonInput)


def module_state(state: State) -> ModuleState:
    return ModuleState(state, REGISTRATION, USER)


# --- Eintragsart und Vorgang ------------------------------------------------------------------


def test_one_entry_per_user_and_year(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    first = YearPersonInput(owner=USER, year=2025, occupation="Beispielberuf")
    assert isinstance(store.apply([Put(first)]), Applied)
    second = store.apply([Put(YearPersonInput(owner=USER, year=2025, phone="123"))])
    assert isinstance(second, Rejected)
    assert "2025" in " ".join(second.reasons.values())
    assert isinstance(store.apply([Put(YearPersonInput(owner=USER, year=2024))]), Applied)
    assert isinstance(store.apply([Put(YearPersonInput(owner="berta", year=2025))]), Applied)


def test_the_operation_rejects_a_phone_number_with_letters(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    result = store.apply([Put(YearPersonInput(owner=USER, year=2025, phone="anrufen"))])
    assert isinstance(result, Rejected)
    assert "Telefon" in " ".join(result.reasons.values())


def test_the_entry_lives_in_the_year_file(tmp_path: Path) -> None:
    open_store(tmp_path, REGISTRATION.kinds).apply(
        [Put(YearPersonInput(owner=USER, year=2025, occupation="Beispielberuf"))]
    )
    assert (tmp_path / "users" / USER / "tax_year" / "2025.json").exists()


# --- reiner Kern ----------------------------------------------------------------------------------


def test_changes_create_update_and_remove() -> None:
    state = ModuleState(State({}), REGISTRATION, USER)
    (create,) = year_person_input_changes(state, 2025, " Beispielberuf ", "", "Ich", "")
    assert isinstance(create, Put) and isinstance(create.entry, YearPersonInput)
    entry = create.entry
    assert (entry.occupation, entry.phone, entry.in_this_return) == ("Beispielberuf", None, "Ich")

    known = module_state(State({e.address: e for e in [entry]}))
    (update,) = year_person_input_changes(known, 2025, "Anderer Beruf", "", "Ich", "")
    assert isinstance(update, Put) and update.expected is not None

    assert year_person_input_changes(known, 2025, "", " ", "", "")[0].__class__.__name__ == "Delete"
    assert (
        year_person_input_changes(ModuleState(State({}), REGISTRATION, USER), 2025, "", "", "", "")
        == []
    )


# --- Seite ---------------------------------------------------------------------------------------


def test_the_overview_saves_and_shows_the_inputs(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert 'name="occupation"' in client.get("/steuerjahr").text
    response = client.post("/steuerjahr/person/2025", data=FIELDS, headers=ORIGIN)
    assert response.status_code == 303
    (saved,) = stored(tmp_path)
    assert (saved.year, saved.occupation, saved.in_this_return) == (2025, "Beispielberuf", CHOICE)
    client.cookies.set("jahr", "2025")
    page = client.get("/steuerjahr").text
    assert "Beispielberuf" in page and "+49 (0) 123 4567-89" in page


def test_a_rejected_phone_number_stays_on_the_page(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.post(
        "/steuerjahr/person/2025", data={**FIELDS, "phone": "anrufen"}, headers=ORIGIN
    )
    assert response.status_code == 422
    assert "Telefon" in response.text and "anrufen" in response.text
    assert stored(tmp_path) == []


def test_clearing_all_fields_removes_the_entry(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    client.post("/steuerjahr/person/2025", data=FIELDS, headers=ORIGIN)
    cleared = {"occupation": "", "phone": "", "in_return": "", "note": ""}
    assert client.post("/steuerjahr/person/2025", data=cleared, headers=ORIGIN).status_code == 303
    assert stored(tmp_path) == []


def test_an_unknown_year_is_not_found(tmp_path: Path) -> None:
    response = client_for(tmp_path).post("/steuerjahr/person/1800", data=FIELDS, headers=ORIGIN)
    assert response.status_code == 404


@pytest.mark.parametrize("year", [2024, 2025])
def test_inputs_are_per_year(tmp_path: Path, year: int) -> None:
    client = client_for(tmp_path)
    client.post(f"/steuerjahr/person/{year}", data=FIELDS, headers=ORIGIN)
    assert [e.year for e in stored(tmp_path)] == [year]


# --- Persönliche Bearbeitungsnotiz (#203) ------------------------------------------------------


NOTE = "Zeile eins\nZeile zwei"


def test_the_note_allows_600_characters_and_the_operation_rejects_more(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    ok = store.apply([Put(YearPersonInput(owner=USER, year=2025, note="x" * 600))])
    assert isinstance(ok, Applied)
    too_long = store.apply([Put(YearPersonInput(owner=USER, year=2025, note="x" * 601))])
    assert isinstance(too_long, Rejected)
    assert "Bearbeitungsnotiz" in " ".join(too_long.reasons.values())


def test_an_entry_saved_without_a_note_loads(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    store.apply([Put(YearPersonInput(owner=USER, year=2025, occupation="Beispielberuf"))])
    (loaded,) = stored(tmp_path)
    assert loaded.note is None


def test_the_note_alone_makes_an_entry_and_keeps_line_breaks() -> None:
    state = ModuleState(State({}), REGISTRATION, USER)
    (create,) = year_person_input_changes(state, 2025, "", "", "", " Zeile eins\r\nZeile zwei \n")
    assert isinstance(create, Put) and isinstance(create.entry, YearPersonInput)
    assert create.entry.note == NOTE


def test_the_overview_saves_the_note_with_line_breaks(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert "<textarea" in client.get("/steuerjahr").text
    assert 'maxlength="600"' in client.get("/steuerjahr").text
    client.post("/steuerjahr/person/2025", data={**FIELDS, "note": "A\r\nB"}, headers=ORIGIN)
    (saved,) = stored(tmp_path)
    assert saved.note == "A\nB"
    client.cookies.set("jahr", "2025")
    assert "A\nB</textarea>" in client.get("/steuerjahr").text


def test_a_too_long_note_is_rejected_on_the_page_and_kept_typed(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.post(
        "/steuerjahr/person/2025", data={**FIELDS, "note": "y" * 601}, headers=ORIGIN
    )
    assert response.status_code == 422
    assert stored(tmp_path) == []
