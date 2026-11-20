"""Tests der Modulanmeldung, des eingegrenzten Stands und des Moduls Arbeit (nur tmp_path)."""

import datetime
import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules import MODULES, ModuleState
from moarcoal.modules.work import (
    REGISTRATION,
    BusinessTrip,
    FirstWorkplace,
    Place,
    TripsConfirmation,
    UserInput,
    WageTaxCertificate,
    WorkEquipment,
)
from moarcoal.modules.work.workplace.forms import HINTS, build_equipment
from moarcoal.modules.work.workplace.values import EQUIPMENT as EQUIPMENT_KEY
from moarcoal.modules.work.workplace.values import EQUIPMENT_GAP, HOMEOFFICE_DAYS
from moarcoal.registration import ForeignKindError, ModuleRegistration
from moarcoal.storage import Applied, Entry, EntryAddress, Put, entry_checksum, open_store
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    NotYetComputable,
    Period,
    Subject,
    Unit,
    format_eur,
    parse_cents,
)
from moarcoal.values.testing import evaluate

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
WORKPLACE = {"year": "2025", "workdays": "180", "distance_km": "12", "description": "Büro"}
EQUIPMENT = {
    "year": "2025",
    "amount": "49,90",
    "date": "2025-03-14",
    "description": "Schreibtischlampe",
}


def make_client(root: Path, user: str = "anna") -> httpx.Client:
    app = make_app(PORT, root, user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def only_id_in(root: Path, year: int) -> str:
    entries = json.loads(work_file(root, year=year).read_text(encoding="utf-8"))["entries"]
    (key,) = entries
    return key.split(":")[1]


def work_file(root: Path, user: str = "anna", year: int = 2025) -> Path:
    return root / "users" / user / "work" / f"{year}.json"


def stored(root: Path) -> dict[str, dict[str, object]]:
    return json.loads(work_file(root).read_text(encoding="utf-8"))["entries"]


def only_id(root: Path) -> str:
    (key,) = stored(root)
    return key.split(":")[1]


def entry_form(client: httpx.Client, slug: str, entry_id: str) -> str:
    """Das aufgeklappte Formular eines Eintrags, erreicht über seine Adresse."""
    response = client.get(f"/arbeit/{slug}/{entry_id}", follow_redirects=True)
    assert response.status_code == 200
    opened = f'<details class="formular-eintrag" open id="eintrag-{entry_id}">'
    assert opened in response.text
    return response.text.split(opened, 1)[1].split("</details>", 1)[0]


def checksum_in(form: str) -> str:
    found = re.search(r'name="checksum" value="([0-9a-f]{64})"', form)
    assert found
    return found.group(1)


# --- Modulanmeldung ---------------------------------------------------------------------------


def test_work_module_is_in_the_fixed_list() -> None:
    assert "work" in [m.key for m in MODULES]
    assert REGISTRATION.area_name == "Arbeit"
    assert {k.model for k in REGISTRATION.kinds} == {
        FirstWorkplace,
        WorkEquipment,
        WageTaxCertificate,
        BusinessTrip,
        TripsConfirmation,
        Place,
    }


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
    [
        ("49,90", 4990),
        ("49,9", 4990),
        ("1.234,56", 123456),
        ("12", 1200),
        (" 0,01 ", 1),
        ("5 €", 500),
    ],
)
def test_parse_cents(text: str, cents: int) -> None:
    assert parse_cents(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "1,234", "NaN", "inf", "12.5", "1e3", "1.2.3"])
def test_parse_cents_rejects(text: str) -> None:
    assert parse_cents(text) is None


def test_equipment_amount_with_point_as_decimal_separator_is_rejected() -> None:
    """„12.5“ ist nicht 125 €: der Betrag wird abgewiesen, statt still falsch gespeichert."""
    entry, errors = build_equipment(
        {"year": "2025", "amount": "12.5", "date": "2025-03-01", "description": "Maus"},
        "anna",
        "AAAAAAAAAA",
    )
    assert entry is None
    assert errors == [HINTS["amount_cents"]]


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
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]


def test_create_workplace_lands_in_data_dir(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/arbeit/erste-taetigkeitsstaette", data=WORKPLACE, headers=ORIGIN)
    assert response.status_code == 303
    (entry,) = stored(tmp_path).values()
    assert entry["workdays"] == 180 and entry["distance_km"] == 12 and entry["owner"] == "anna"
    page = client.get("/arbeit").text
    assert "180" in page and "12 km" in page and "Büro" in page


def purchase(year: int, cents: int = 4990) -> WorkEquipment:
    return WorkEquipment(
        owner="anna",
        year=year,
        input=UserInput(amount_cents=cents, date=datetime.date(year, 3, 14), description="Lampe"),
    )


def equipment_2025(items: list[Entry]) -> tuple[object, list[Finding]]:
    values = evaluate([REGISTRATION], items)
    value = values.get(EQUIPMENT_KEY, "anna", Period.year(2025))
    found = values.finding_list("anna", 2025).visible
    return value, [f for f in found if f.kind == EQUIPMENT_GAP]  # Dienstreisen: eigene Tests


def test_no_equipment_this_or_previous_year_is_zero_without_finding() -> None:
    value, found = equipment_2025([])

    assert isinstance(value, ExposedValue)
    assert value.amount == Amount.of(Decimal(0), Unit.EUR)
    assert value.items == ()
    assert any("auch im Vorjahr 2024 keine" in s.text for s in value.workings.steps)
    assert found == []


def test_no_equipment_after_previous_year_with_equipment_is_zero_with_note() -> None:
    value, found = equipment_2025([purchase(2024)])

    assert isinstance(value, ExposedValue)
    assert value.amount == Amount.of(Decimal(0), Unit.EUR)
    (note,) = found
    assert note.kind == EQUIPMENT_GAP and note.severity is Severity.NOTE
    assert "2024" in note.message and "2025" in note.message
    assert note.href == "/arbeit?jahr=2025"  # das Jahr des Befunds, nicht das globale


def test_equipment_this_year_gives_no_note() -> None:
    value, found = equipment_2025([purchase(2024), purchase(2025)])

    assert isinstance(value, ExposedValue) and value.amount.value == Decimal("49.90")
    assert found == []


def test_year_without_equipment_shows_zero(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/erste-taetigkeitsstaette", data=WORKPLACE, headers=ORIGIN)
    page = client.get("/arbeit").text.split("<h2>Arbeitsmittel</h2>")[1].split("</section>")[0]
    assert "noch nicht berechenbar" not in page
    assert "keine Arbeitsmittel erfasst" in page
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    assert "keine Arbeitsmittel erfasst" not in client.get("/arbeit").text


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
    changed = EQUIPMENT | {
        "amount": "59,90",
        "checksum": checksum_in(entry_form(client, "arbeitsmittel", entry_id)),
    }
    saved = client.post(url, data=changed, headers=ORIGIN)
    assert saved.status_code == 303 and saved.headers["location"] == "/arbeit?jahr=2025"
    assert next(iter(stored(tmp_path).values()))["input"]["amount_cents"] == 5990  # type: ignore[index]

    checksum = checksum_in(entry_form(client, "arbeitsmittel", entry_id))
    gone = client.post(f"{url}/loeschen", data={"checksum": checksum}, headers=ORIGIN)
    assert gone.status_code == 303
    assert not work_file(tmp_path).exists()
    assert client.get(url).status_code == 404


def test_the_address_of_an_entry_opens_it_on_arbeit_in_its_year(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT | {"year": "2024"}, headers=ORIGIN)
    entry_id = only_id_in(tmp_path, 2024)
    response = client.get(f"/arbeit/arbeitsmittel/{entry_id}")
    assert response.status_code == 303
    assert response.headers["location"] == f"/arbeit?jahr=2024&eintrag={entry_id}"
    page = client.get("/arbeit?jahr=2024").text
    assert f'<details class="formular-eintrag" id="eintrag-{entry_id}">' in page  # zu, ohne Wahl


def test_arbeit_shows_only_the_entries_of_its_year_and_new_ones_get_that_year(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT | {"year": "2024"}, headers=ORIGIN)
    assert "Schreibtischlampe" not in client.get("/arbeit?jahr=2025").text
    page = client.get("/arbeit?jahr=2024").text
    assert "Schreibtischlampe" in page
    assert 'name="year" value="2024"' in page and "<label>Steuerjahr" not in page  # kein Feld dafür


def test_the_tax_year_of_an_entry_stays(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    entry_id = only_id(tmp_path)
    checksum = checksum_in(entry_form(client, "arbeitsmittel", entry_id))
    moved = EQUIPMENT | {"year": "2024", "amount": "1,00", "checksum": checksum}
    response = client.post(f"/arbeit/arbeitsmittel/{entry_id}", data=moved, headers=ORIGIN)
    assert response.status_code == 303 and response.headers["location"] == "/arbeit?jahr=2025"
    assert next(iter(stored(tmp_path).values()))["year"] == 2025


def test_a_rejected_change_shows_arbeit_with_the_form_open(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    entry_id = only_id(tmp_path)
    checksum = checksum_in(entry_form(client, "arbeitsmittel", entry_id))
    bad = EQUIPMENT | {"amount": "abc", "checksum": checksum}
    response = client.post(f"/arbeit/arbeitsmittel/{entry_id}", data=bad, headers=ORIGIN)
    assert response.status_code == 422
    opened = f'<details class="formular-eintrag" open id="eintrag-{entry_id}">'
    form = response.text.split(opened, 1)[1].split("</details>", 1)[0]
    assert "Betrag" in form and 'value="abc"' in form and checksum in form
    assert "Lohnsteuerbescheinigung" in response.text  # die ganze Seite


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
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]


def test_stale_form_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/arbeitsmittel", data=EQUIPMENT, headers=ORIGIN)
    entry_id = only_id(tmp_path)
    url = f"/arbeit/arbeitsmittel/{entry_id}"
    checksum = checksum_in(entry_form(client, "arbeitsmittel", entry_id))
    first = EQUIPMENT | {"amount": "10,00", "checksum": checksum}
    second = EQUIPMENT | {"amount": "20,00", "checksum": checksum}
    assert client.post(url, data=first, headers=ORIGIN).status_code == 303
    response = client.post(url, data=second, headers=ORIGIN)
    assert response.status_code == 409
    assert "Inzwischen geändert" in response.text


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
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]


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
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]
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
    form = entry_form(client, "erste-taetigkeitsstaette", only_id(tmp_path))
    assert 'name="workdays" inputmode="numeric" value="180"' in form


def test_display_name_is_shown_in_the_header(tmp_path: Path) -> None:
    assert "Max Mustermann" in make_client(tmp_path).get("/arbeit").text


def test_workplace_inputs_are_optional_and_stored(tmp_path: Path) -> None:
    http = make_client(tmp_path)
    http.post("/arbeit/erste-taetigkeitsstaette", data=WORKPLACE, headers=ORIGIN)
    (entry,) = stored(tmp_path).values()
    assert entry.get("workdays_per_week") is None and entry.get("car_distance_km") is None

    entry_id = only_id(tmp_path)
    checksum = checksum_in(entry_form(http, "erste-taetigkeitsstaette", entry_id))
    extra = {
        **WORKPLACE,
        "workdays_per_week": "5",
        "absence_days": "32",
        "homeoffice_days": "40",
        "car_distance_km": "11",
    }
    response = http.post(
        f"/arbeit/erste-taetigkeitsstaette/{entry_id}",
        data={**extra, "checksum": checksum},
        headers=ORIGIN,
    )
    assert response.status_code == 303
    (entry,) = stored(tmp_path).values()
    assert entry["workdays_per_week"] == 5 and entry["absence_days"] == 32
    assert entry["homeoffice_days"] == 40
    form = entry_form(http, "erste-taetigkeitsstaette", entry_id)
    assert 'name="homeoffice_days"' in form and 'value="40"' in form
    assert entry["car_distance_km"] == 11


def test_workplace_inputs_are_validated(tmp_path: Path) -> None:
    http = make_client(tmp_path)
    bad_inputs = (
        ("workdays_per_week", "8"),
        ("absence_days", "-1"),
        ("homeoffice_days", "367"),
        ("car_distance_km", "13"),
    )
    for name, bad in bad_inputs:
        response = http.post(
            "/arbeit/erste-taetigkeitsstaette", data={**WORKPLACE, name: bad}, headers=ORIGIN
        )
        assert response.status_code == 422
        assert (
            name != "homeoffice_days"
            or "Homeoffice-Tage: ganze Zahl von 0 bis 366" in response.text
        )
    assert not work_file(tmp_path).exists()


def test_workplace_without_the_new_fields_still_loads() -> None:
    entry = FirstWorkplace(owner="anna", year=2025, workdays=180, distance_km=12)
    assert entry.workdays_per_week is None and entry.absence_days is None


# --- Homeoffice-Tage (Nr. 58) -------------------------------------------------------------------


def homeoffice_days(days: int | None) -> object:
    place = FirstWorkplace(
        owner="anna", year=2025, workdays=180, distance_km=12, homeoffice_days=days
    )
    subject = Subject(place.address)
    return evaluate([REGISTRATION], [place]).get(
        HOMEOFFICE_DAYS, "anna", Period.year(2025), subject
    )


def test_homeoffice_days_come_from_the_workplace() -> None:
    result = homeoffice_days(40)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.of(40, Unit.DAYS)


def test_zero_homeoffice_days_are_a_value() -> None:
    result = homeoffice_days(0)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.of(0, Unit.DAYS)


def test_empty_homeoffice_days_are_not_yet_computable_never_zero() -> None:
    result = homeoffice_days(None)

    assert isinstance(result, NotYetComputable)
    assert "Homeoffice-Tage" in result.reason
