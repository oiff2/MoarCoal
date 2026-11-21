"""Tests: Eingaben zu Eintippfeldern der Anlage N (Nr. 27 Ziel des Weges, Nr. 65 Firmenwagen)."""

import json
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_n import YES_NO
from moarcoal.modules.tax_year.entries import FormInput
from moarcoal.modules.tax_year.fields import TypedInput
from moarcoal.storage import Applied, Put, Rejected, StoreError, open_store

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
CAR = "/steuerjahr/anlage-n/2025/eingabe/E0204901"


def entered(elster_id: str, content: str, year: int = 2025) -> FormInput:
    return FormInput(owner="anna", year=year, elster_id=elster_id, content=content)


def make_client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def stored(root: Path) -> dict[str, dict[str, object]]:
    path = root / "users" / "anna" / "tax_year" / "2025.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


# --- Prüfung der Eingabe ------------------------------------------------------------------------


def test_choices_accept_only_the_listed_texts() -> None:
    assert TypedInput(YES_NO).check("Ja", 2025) is None
    assert TypedInput(YES_NO).check("Vielleicht", 2025) is not None


def test_free_text_accepts_any_text() -> None:
    assert TypedInput().check("12345 Musterstadt, Beispielweg 1", 2025) is None


@pytest.mark.parametrize("text", ["01.01-31.12", "29.02-29.02"])
def test_day_range_accepts_days_of_the_year_in_order(text: str) -> None:
    year = 2024 if text.startswith("29.02") else 2025
    assert TypedInput(day_range=True).check(text, year) is None


@pytest.mark.parametrize(
    "text", ["1.1-31.12", "01.01.-31.12.", "31.02-01.03", "01.05-01.04", "29.02-01.03", "Januar"]
)
def test_day_range_rejects_other_formats_and_impossible_days(text: str) -> None:
    assert TypedInput(day_range=True).check(text, 2025) is not None


def test_a_day_range_cannot_also_have_choices() -> None:
    with pytest.raises(ValueError, match="Auswahl"):
        TypedInput(("a",), day_range=True)


# --- Schreibweg ---------------------------------------------------------------------------------


def test_only_one_input_per_field_and_year_is_accepted_by_the_write_path(tmp_path: Path) -> None:
    store = open_store(tmp_path, TAX_YEAR.kinds)
    assert isinstance(store.apply([Put(entered("E0204901", "Ja"))]), Applied)

    again = store.apply([Put(entered("E0204901", "Nein"))])

    assert isinstance(again, Rejected) and "schon eine Eingabe" in " ".join(again.reasons.values())


@pytest.mark.parametrize(
    ("elster_id", "content", "year"),
    [
        ("E0204901", "Vielleicht", 2025),
        ("E0204507", "20", 2025),
        ("E0204901", "Ja", 2024),
        ("E0203003", "Arbeitsplatz", 2025),
        ("E0203101", "1.1.-31.12.", 2025),
        ("E0203101", "01.07-30.06", 2025),
    ],
)
def test_the_write_path_rejects_an_input_that_does_not_fit_the_field(
    tmp_path: Path, elster_id: str, content: str, year: int
) -> None:
    store = open_store(tmp_path, TAX_YEAR.kinds)

    result = store.apply([Put(entered(elster_id, content, year))])

    assert isinstance(result, Rejected)


@pytest.mark.parametrize(
    ("elster_id", "content"),
    [
        ("E0203003", "erste Tätigkeitsstätte"),
        ("E0203501", "12345 Musterstadt, Beispielweg 1"),
        ("E0203101", "01.01-31.12"),
        ("E0205003", "Pkw 100km"),
    ],
)
def test_the_write_path_accepts_inputs_to_nr_27_and_travel_fare_kind(
    tmp_path: Path, elster_id: str, content: str
) -> None:
    store = open_store(tmp_path, TAX_YEAR.kinds)

    assert isinstance(store.apply([Put(entered(elster_id, content))]), Applied)


# --- Laden: Eingaben zu Feldern, die keine Eingabe mehr nehmen -----------------------------------


def test_an_old_input_to_homeoffice_days_stops_the_start_and_names_the_file(tmp_path: Path) -> None:
    old = entered("E0204507", "20")  # Nr. 58 kommt jetzt aus Arbeit
    path = tmp_path / "users" / "anna" / "tax_year" / "2025.json"
    path.parent.mkdir(parents=True)
    body = {"schema": "tax_year/1", "entries": {str(old.address): old.model_dump(mode="json")}}
    path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(StoreError, match="users/anna/tax_year/2025.json"):
        open_store(tmp_path, TAX_YEAR.kinds)


# --- Seite --------------------------------------------------------------------------------------


def test_homeoffice_days_have_no_input_on_the_page(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/steuerjahr/anlage-n/2025/12").text

    assert "eingabe/E0204507" not in page
    assert "Homeoffice" in page


def test_company_car_takes_only_the_choices_and_stays_unanswered_by_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/steuerjahr/anlage-n/2025/15").text
    assert "noch nicht angegeben" in page and '<option value="Ja"' in page
    assert " selected" not in page.split("<main>", 1)[1]

    client.post(CAR, data={"content": "Vielleicht"}, headers=ORIGIN)
    assert stored(tmp_path) == {}

    response = client.post(CAR, data={"content": "Nein"}, headers=ORIGIN)
    assert '<option value="Nein" selected>' in response.text
    (entry,) = stored(tmp_path).values()
    assert entry["content"] == "Nein" and entry["elster_id"] == "E0204901"


def test_nr_27_takes_its_choices_and_free_text(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/steuerjahr/anlage-n/2025/wege-zwischen-wohnung").text
    assert '<option value="Sammelpunkt / weiträumiges Tätigkeitsgebiet"' in page
    assert 'name="content" type="text"' in page and 'placeholder="TT.MM-TT.MM"' in page

    bad = client.post(
        "/steuerjahr/anlage-n/2025/eingabe/E0203101",
        data={"content": "1.1.-31.12."},
        headers=ORIGIN,
    )
    assert "TT.MM-TT.MM" in bad.text and stored(tmp_path) == {}

    client.post(
        "/steuerjahr/anlage-n/2025/eingabe/E0203501",
        data={"content": "12345 Musterstadt, Beispielweg 1"},
        headers=ORIGIN,
    )
    (entry,) = stored(tmp_path).values()
    assert entry["content"] == "12345 Musterstadt, Beispielweg 1"


def test_field_without_input_and_unknown_year_are_not_found(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert (
        client.post(
            "/steuerjahr/anlage-n/2025/eingabe/E0200201", data={"content": "1"}, headers=ORIGIN
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/steuerjahr/anlage-n/1999/eingabe/E0204507", data={"content": "1"}, headers=ORIGIN
        ).status_code
        == 404
    )
