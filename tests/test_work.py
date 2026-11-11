"""Tests der Modulanmeldung, des eingegrenzten Stands und des Moduls Arbeit (nur tmp_path)."""

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules import MODULES, ModuleState
from moarcoal.modules.work import REGISTRATION, FirstWorkplace, UserInput, WorkEquipment
from moarcoal.modules.work.pages import parse_cents
from moarcoal.registration import ForeignKindError, ModuleRegistration
from moarcoal.storage import Applied, EntryAddress, Put, entry_checksum, open_store
from moarcoal.web import format_eur

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
WORKPLACE = {"year": "2025", "workdays": "180", "distance_km": "12", "description": "Büro"}
EQUIPMENT = {
    "year": "2025",
    "amount": "49,90",
    "date": "2025-03-14",
    "description": "Schreibtischlampe",
}


def make_client(root: Path, user: str = "anna", user_name: str = "Max Mustermann") -> httpx.Client:
    app = create_app(PORT, root, user=user, user_name=user_name)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def work_file(root: Path, user: str = "anna", year: int = 2025) -> Path:
    return root / "nutzer" / user / "work" / f"{year}.json"


def stored(root: Path) -> dict[str, dict[str, object]]:
    return json.loads(work_file(root).read_text(encoding="utf-8"))["entries"]


def only_id(root: Path) -> str:
    (key,) = stored(root)
    return key.split(":")[1]


# --- Modulanmeldung ---------------------------------------------------------------------------


def test_work_module_is_in_the_fixed_list() -> None:
    assert [m.key for m in MODULES] == ["work"]
    assert REGISTRATION.area_name == "Arbeit"
    assert {k.model for k in REGISTRATION.kinds} == {FirstWorkplace, WorkEquipment}


def test_registration_maps_entry_to_path_and_schema(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    entry = FirstWorkplace(owner="anna", year=2025, workdays=100, distance_km=5)
    assert isinstance(store.apply([Put(entry)]), Applied)
    written = json.loads(work_file(tmp_path).read_text(encoding="utf-8"))
    assert written["schema"] == "work/1"
    assert str(entry.address) in written["entries"]


def test_module_state_is_limited_to_own_kinds_and_user(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    mine = FirstWorkplace(owner="anna", year=2025, workdays=100, distance_km=5)
    theirs = FirstWorkplace(owner="ben", year=2025, workdays=90, distance_km=7)
    store.apply([Put(mine), Put(theirs)])
    state = ModuleState(store.state(), REGISTRATION, "anna")
    assert state.all(FirstWorkplace) == [mine]
    assert state.get(mine.address) == mine
    assert state.get(theirs.address) is None
    assert state.checksum(mine.address) == entry_checksum(mine)
    assert state.all(WorkEquipment) == []


def test_module_state_refuses_foreign_kinds(tmp_path: Path) -> None:
    store = open_store(tmp_path, REGISTRATION.kinds)
    other = ModuleRegistration("other", "Anderes", "Anderes", "/x", REGISTRATION.router, ())
    state = ModuleState(store.state(), other, "anna")
    with pytest.raises(ForeignKindError):
        state.all(FirstWorkplace)
    with pytest.raises(ForeignKindError):
        state.get(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))


# --- Eingaben ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cents"),
    [("49,90", 4990), ("49,9", 4990), ("1.234,56", 123456), ("12", 1200), (" 0,01 ", 1)],
)
def test_parse_cents(text: str, cents: int) -> None:
    assert parse_cents(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "1,234", "NaN", "inf"])
def test_parse_cents_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_cents(text)


def test_format_eur() -> None:
    assert format_eur(123456) == "1.234,56 €"
    assert format_eur(5) == "0,05 €"


def test_user_input_needs_positive_amount_and_description() -> None:
    with pytest.raises(ValueError):
        UserInput.model_validate({"amount_cents": 0, "date": "2025-01-01", "description": "x"})
    with pytest.raises(ValueError):
        UserInput.model_validate({"amount_cents": 1, "date": "2025-01-01", "description": ""})


# --- Seite: erfassen, ändern, löschen ----------------------------------------------------------


def test_overview_is_empty_and_has_links(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/arbeit")
    assert response.status_code == 200
    assert "Erste Tätigkeitsstätte" in response.text
    assert "Arbeitsmittel" in response.text
    assert "<script>" not in response.text
    assert list(tmp_path.iterdir()) == []  # GET schreibt nie


def test_create_workplace_lands_in_data_dir(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/arbeit/erste-taetigkeitsstaette", data=WORKPLACE, headers=ORIGIN)
    assert response.status_code == 303
    (entry,) = stored(tmp_path).values()
    assert entry["workdays"] == 180 and entry["distance_km"] == 12 and entry["owner"] == "anna"
    page = client.get("/arbeit").text
    assert "180" in page and "12 km" in page and "Büro" in page


def test_create_equipment_stores_cents(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    assert response.status_code == 303
    (entry,) = stored(tmp_path).values()
    assert entry["input"] == {
        "amount_cents": 4990,
        "date": "2025-03-14",
        "description": "Schreibtischlampe",
    }
    assert "49,90 €" in client.get("/arbeit").text


def test_change_and_delete(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    entry_id = only_id(tmp_path)
    url = f"/arbeit/arbeitsmittel/{entry_id}"
    form = client.get(url).text
    checksum = re.search(r'name="checksum" value="([0-9a-f]{64})"', form)
    assert checksum
    changed = EQUIPMENT | {"amount": "59,90", "checksum": checksum.group(1)}
    assert client.post(url, data=changed, headers=ORIGIN).status_code == 303
    assert next(iter(stored(tmp_path).values()))["input"]["amount_cents"] == 5990  # type: ignore[index]

    new_checksum = re.search(r'name="checksum" value="([0-9a-f]{64})"', client.get(url).text)
    assert new_checksum
    gone = client.post(f"{url}/loeschen", data={"checksum": new_checksum.group(1)}, headers=ORIGIN)
    assert gone.status_code == 303
    assert not work_file(tmp_path).exists()
    assert client.get(url).status_code == 404


def test_invalid_input_shows_german_hints_and_writes_nothing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    bad = {"year": "1999", "workdays": "400", "distance_km": "x", "description": ""}
    response = client.post("/arbeit/erste-taetigkeitsstaette", data=bad, headers=ORIGIN)
    assert response.status_code == 422
    for hint in ("Steuerjahr", "Arbeitstage", "Einfache Entfernung"):
        assert hint in response.text
    assert 'value="400"' in response.text  # Eingabe bleibt stehen
    bad_equipment = EQUIPMENT | {"amount": "abc", "description": ""}
    response = client.post("/arbeit/arbeitsmittel", data=bad_equipment, headers=ORIGIN)
    assert response.status_code == 422
    assert "Betrag" in response.text and "Beschreibung" in response.text
    assert list(tmp_path.iterdir()) == []


def test_stale_form_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    url = f"/arbeit/arbeitsmittel/{only_id(tmp_path)}"
    checksum = re.search(r'name="checksum" value="([0-9a-f]{64})"', client.get(url).text)
    assert checksum
    first = EQUIPMENT | {"amount": "10,00", "checksum": checksum.group(1)}
    second = EQUIPMENT | {"amount": "20,00", "checksum": checksum.group(1)}
    assert client.post(url, data=first, headers=ORIGIN).status_code == 303
    response = client.post(url, data=second, headers=ORIGIN)
    assert response.status_code == 409
    assert "Inzwischen geändert" in response.text
    assert next(iter(stored(tmp_path).values()))["input"]["amount_cents"] == 1000  # type: ignore[index]


def test_unknown_kind_and_entry_are_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/arbeit/gibt-es-nicht/AAAAAAAAAA").status_code == 404
    assert client.get("/arbeit/arbeitsmittel/AAAAAAAAAA").status_code == 404
    assert client.get("/arbeit/arbeitsmittel/zu-kurz").status_code == 404
    response = client.post("/arbeit/gibt-es-nicht", data={}, headers=ORIGIN)
    assert response.status_code == 404


def test_entries_of_another_user_are_not_reachable(tmp_path: Path) -> None:
    make_client(tmp_path, "anna").post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    entry_id = only_id(tmp_path)
    ben = make_client(tmp_path, "ben")
    assert ben.get(f"/arbeit/arbeitsmittel/{entry_id}").status_code == 404
    assert "Schreibtischlampe" not in ben.get("/arbeit").text


def test_posts_need_same_origin(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/arbeit/arbeitsmittel", data=EQUIPMENT).status_code == 403
    foreign = {"Origin": "http://evil.example"}
    assert client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=foreign).status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_text_is_escaped(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = EQUIPMENT | {"description": "<b>fett</b>"}
    client.post("/arbeit/arbeitsmittel", data=data, headers=ORIGIN)
    page = client.get("/arbeit").text
    assert "<b>fett</b>" not in page and "&lt;b&gt;fett&lt;/b&gt;" in page


def test_workdays_limit_is_250(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    over = client.post(
        "/arbeit/erste-taetigkeitsstaette", data=WORKPLACE | {"workdays": "251"}, headers=ORIGIN
    )
    assert over.status_code == 422 and "bis 250" in over.text
    assert list(tmp_path.iterdir()) == []
    at_limit = client.post(
        "/arbeit/erste-taetigkeitsstaette", data=WORKPLACE | {"workdays": "250"}, headers=ORIGIN
    )
    assert at_limit.status_code == 303


def test_new_workplace_form_prefills_220_but_edit_keeps_stored_value(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert 'name="workdays" inputmode="numeric" value="220"' in client.get("/arbeit").text
    client.post(
        "/arbeit/erste-taetigkeitsstaette", data=WORKPLACE | {"workdays": "180"}, headers=ORIGIN
    )
    page = client.get(f"/arbeit/erste-taetigkeitsstaette/{only_id(tmp_path)}").text
    assert 'name="workdays" inputmode="numeric" value="180"' in page


def test_display_name_is_shown_and_replaceable(tmp_path: Path) -> None:
    assert "Max Mustermann" in make_client(tmp_path).get("/arbeit").text
    other = make_client(tmp_path, user_name="Erika Beispiel")
    assert "Erika Beispiel" in other.get("/").text
