"""Tests: Eingaben zu Eintippfeldern der Anlage N (Nr. 58 Homeoffice-Tage, Nr. 65 Firmenwagen)."""

import json
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_n import (
    FIELDS_2025,
    N_ABSENCE_DAYS,
    N_HOMEOFFICE_DAYS,
    WORK_ABSENCE_DAYS,
    WORK_TRIP_DAYS,
    WORK_WORKDAYS,
    YES_NO,
)
from moarcoal.modules.tax_year.entries import FormInput
from moarcoal.modules.tax_year.fields import TypedInput
from moarcoal.storage import Applied, EntryAddress, Put, Rejected, open_store
from moarcoal.values.engine import Foreign
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    NotYetComputable,
    Period,
    Subject,
    Unit,
    UserInputLocator,
)
from moarcoal.values.testing import evaluate, fixed

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)
PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))
HOME = "/steuerjahr/anlage-n/2025/eingabe/E0204507"
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


@pytest.mark.parametrize("text", ["0", "20", "366"])
def test_days_accept_whole_numbers_in_range(text: str) -> None:
    assert TypedInput().check(text) is None


@pytest.mark.parametrize("text", ["367", "-1", "1,5", "abc", "²"])
def test_days_reject_everything_else(text: str) -> None:
    assert TypedInput().check(text) is not None


def test_choices_accept_only_the_listed_texts() -> None:
    assert TypedInput(YES_NO).check("Ja") is None
    assert TypedInput(YES_NO).check("Vielleicht") is not None


# --- Werte --------------------------------------------------------------------------------------


def test_homeoffice_days_without_input_are_not_yet_computable_never_zero() -> None:
    result = evaluate([TAX_YEAR]).get(N_HOMEOFFICE_DAYS, "anna", YEAR)

    assert isinstance(result, NotYetComputable)
    assert "Nr. 58" in result.reason


def test_homeoffice_days_show_the_input_as_assumed_line_item() -> None:
    entry = entered("E0204507", "20")

    result = evaluate([TAX_YEAR], [entry]).get(N_HOMEOFFICE_DAYS, "anna", YEAR)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.of(20, Unit.DAYS)
    (item,) = result.items
    assert item.locator == UserInputLocator(entry.address)
    assert result.backing is Backing.ASSUMED


def test_input_of_another_year_does_not_count() -> None:
    entry = entered("E0204507", "20", year=2024)

    assert isinstance(
        evaluate([TAX_YEAR], [entry]).get(N_HOMEOFFICE_DAYS, "anna", YEAR), NotYetComputable
    )


def test_absence_days_take_the_homeoffice_days_of_the_input() -> None:
    foreign: Foreign = {
        (WORK_WORKDAYS, PLACE, YEAR): fixed(Amount.of(180, Unit.DAYS)),
        (WORK_ABSENCE_DAYS, PLACE, YEAR): fixed(Amount.of(30, Unit.DAYS)),
        (WORK_TRIP_DAYS, None, YEAR): fixed(Amount.of(3, Unit.DAYS)),
    }

    result = evaluate([TAX_YEAR], [entered("E0204507", "20")], foreign).get(
        N_ABSENCE_DAYS, "anna", YEAR
    )

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.of(53, Unit.DAYS)


def test_input_fields_are_marked_in_the_catalog() -> None:
    typed = {f.elster_id: f.typed for f in FIELDS_2025 if f.typed}

    assert set(typed) == {"E0204507", "E0204901"}
    assert typed["E0204901"] == TypedInput(YES_NO)


# --- Schreibweg ---------------------------------------------------------------------------------


def test_only_one_input_per_field_and_year_is_accepted_by_the_write_path(tmp_path: Path) -> None:
    store = open_store(tmp_path, TAX_YEAR.kinds)
    assert isinstance(store.apply([Put(entered("E0204507", "20"))]), Applied)

    again = store.apply([Put(entered("E0204507", "21"))])
    other = store.apply([Put(entered("E0204901", "Ja"))])

    assert isinstance(again, Rejected) and "schon eine Eingabe" in " ".join(again.reasons.values())
    assert isinstance(other, Applied)


# --- Seite --------------------------------------------------------------------------------------


def test_get_shows_the_input_at_the_field_and_writes_nothing(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/steuerjahr/anlage-n/2025/12").text

    assert 'hx-post="' + HOME + '"' in page
    assert "noch nicht berechenbar" in page
    assert not (tmp_path / "users" / "anna" / "tax_year").exists()


def test_post_stores_the_days_and_returns_the_field_with_the_value(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(HOME, data={"content": "20"}, headers=ORIGIN)

    assert response.status_code == 200
    assert "20 Tage" in response.text
    (entry,) = stored(tmp_path).values()
    assert entry["content"] == "20" and entry["elster_id"] == "E0204507"
    assert 'value="20"' in client.get("/steuerjahr/anlage-n/2025/12").text


def test_post_again_replaces_and_empty_text_withdraws_the_input(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(HOME, data={"content": "20"}, headers=ORIGIN)
    client.post(HOME, data={"content": "25"}, headers=ORIGIN)
    assert [e["content"] for e in stored(tmp_path).values()] == ["25"]

    response = client.post(HOME, data={"content": " "}, headers=ORIGIN)

    assert stored(tmp_path) == {}
    assert "noch nicht berechenbar" in response.text


def test_invalid_days_are_refused_with_a_hint_and_change_nothing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(HOME, data={"content": "20"}, headers=ORIGIN)

    response = client.post(HOME, data={"content": "400"}, headers=ORIGIN)

    assert response.status_code == 200  # htmx tauscht Fehlerantworten nicht ein
    assert "ganze Zahl von 0 bis 366" in response.text
    assert [e["content"] for e in stored(tmp_path).values()] == ["20"]


def test_company_car_takes_only_the_choices_and_stays_unanswered_by_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/steuerjahr/anlage-n/2025/15").text
    assert "noch nicht angegeben" in page and '<option value="Ja"' in page
    assert " selected" not in page

    client.post(CAR, data={"content": "Vielleicht"}, headers=ORIGIN)
    assert stored(tmp_path) == {}

    response = client.post(CAR, data={"content": "Nein"}, headers=ORIGIN)
    assert '<option value="Nein" selected>' in response.text
    (entry,) = stored(tmp_path).values()
    assert entry["content"] == "Nein" and entry["elster_id"] == "E0204901"


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
