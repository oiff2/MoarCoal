"""Tests: Dienstreisen (Tabelle, Fahrtkosten, vollständig bestätigen, Anlage N Nr. 66 bis 69).

Alle Orte und Werte sind erfunden; geschrieben wird nur in `tmp_path`.
"""

import datetime
import html
import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_n import (
    N_TRAVEL_FARE,
    N_TRAVEL_INCIDENTALS,
    N_TRAVEL_LODGING,
    N_TRAVEL_TOTAL,
)
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import BusinessTrip, TripsConfirmation
from moarcoal.modules.work.trips.table import (
    TripRow,
    TripTableError,
    confirm_changes,
    current_confirmation,
    km_amount,
    plan_changes,
    rows_from_form,
    split_places,
)
from moarcoal.modules.work.trips.values import (
    TRAVEL_FARE,
    TRAVEL_INCIDENTALS,
    TRAVEL_LODGING,
    TRAVEL_TOTAL,
    TRIPS_TO_FILL,
)
from moarcoal.storage import (
    Applied,
    Delete,
    EntryAddress,
    Put,
    Rejected,
    entry_checksum,
    open_store,
)
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    NotApplicable,
    NotYetComputable,
    Period,
    Unit,
    ValueKey,
)
from moarcoal.values.testing import evaluate

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)
USER = "anna"


def trip(
    day: int = 3, km: int = 100, places: tuple[str, ...] = ("Altstadt", "Neudorf", "Altstadt")
) -> BusinessTrip:
    return BusinessTrip(
        owner=USER,
        year=2025,
        start=datetime.date(2025, 2, day),
        places=places,
        distance_km=km,
    )


def confirmation(trips: list[BusinessTrip]) -> TripsConfirmation:
    return confirm_changes([], trips, 2025, USER, datetime.date(2026, 1, 5))[0].entry  # type: ignore[return-value]


def value(key: str, items: list[object]) -> object:
    return evaluate([WORK], items).get(key, USER, YEAR)  # type: ignore[arg-type]


# --- Modell -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"places": ("Altstadt",)},
        {"distance_km": 0},
        {"start": datetime.date(2024, 12, 31)},
        {"end": datetime.date(2025, 1, 1)},
        {"end": datetime.date(2026, 1, 1)},
        {"places": ("Altstadt", " ")},
    ],
)
def test_trip_rejects_invalid_values(bad: dict[str, object]) -> None:
    good = trip().model_dump() | {"id": "AAAAAAAAAA"}
    with pytest.raises(ValueError):
        BusinessTrip.model_validate(good | bad)


# --- Tabelle ------------------------------------------------------------------------------------


def form(*rows: dict[str, str]) -> dict[str, str]:
    data = {"zeilen": str(len(rows))}
    for n, row in enumerate(rows):
        data |= {f"{name}-{n}": text for name, text in row.items()}
    return data


def plan(*rows: dict[str, str], existing: list[BusinessTrip] | None = None) -> list[Put | Delete]:
    return plan_changes(rows_from_form(form(*rows)), 2025, USER, existing or [])


def test_places_split_on_arrow_semicolon_and_spaced_dash() -> None:
    assert split_places("A → B → A") == ["A", "B", "A"]
    assert split_places("A -> B; A") == ["A", "B", "A"]
    assert split_places("Alt-Stadt - Neudorf") == ["Alt-Stadt", "Neudorf"]


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("03.02.2025", datetime.date(2025, 2, 3)),
        ("3.2.25", datetime.date(2025, 2, 3)),
        ("03.02.", datetime.date(2025, 2, 3)),
        ("2025-02-03", datetime.date(2025, 2, 3)),
    ],
)
def test_date_formats(text: str, day: datetime.date) -> None:
    (change,) = plan({"start": text, "orte": "A → B → A", "km": "12"})
    assert isinstance(change, Put) and isinstance(change.entry, BusinessTrip)
    assert change.entry.start == day and change.entry.end is None and change.entry.year == 2025


def test_new_row_becomes_a_put_and_blank_rows_are_skipped() -> None:
    changes = plan(
        {"start": "03.02.", "ende": "04.02.", "orte": "A → B → A", "km": "40", "notiz": "Kunde"},
        {"orte": "A → "},
    )
    (put,) = changes
    assert isinstance(put, Put) and put.expected is None
    trip_ = put.entry
    assert isinstance(trip_, BusinessTrip)
    assert trip_.places == ("A", "B", "A") and trip_.distance_km == 40 and trip_.note == "Kunde"


def test_invalid_cells_are_marked_and_nothing_is_planned() -> None:
    rows = rows_from_form(
        form(
            {"start": "03.02.", "orte": "A → B → A", "km": "10"},
            {"start": "31.12.2024", "ende": "x", "orte": "A", "km": "0"},
            {"start": "03.02.", "ende": "01.02.", "orte": "A → B", "km": "1,5"},
        )
    )
    with pytest.raises(TripTableError):
        plan_changes(rows, 2025, USER, [])
    assert rows[0].errors == {}
    assert set(rows[1].errors) == {"start", "ende", "orte", "km"}
    assert set(rows[2].errors) == {"ende", "km"}
    assert "Steuerjahr 2025" in rows[1].errors["start"]


def test_unchanged_rows_plan_nothing_changed_rows_carry_the_checksum() -> None:
    saved = trip()
    row = TripRow.from_trip(saved, None)
    data = {
        "start": row.start,
        "orte": row.places,
        "km": row.km,
        "id": saved.id,
        "pruefsumme": row.checksum,
    }
    assert plan(data, existing=[saved]) == []
    (put,) = plan(data | {"km": "120"}, existing=[saved])
    assert isinstance(put, Put) and put.expected == entry_checksum(saved)
    assert put.entry.id == saved.id


def test_delete_ticked_or_blanked_rows_delete_with_the_checksum() -> None:
    saved = trip()
    checksum = entry_checksum(saved)
    ticked = {"start": "03.02.", "orte": "A → B", "km": "5", "id": saved.id, "pruefsumme": checksum}
    expected = [Delete(saved.address, checksum)]
    assert plan(ticked | {"loeschen": "ja"}, existing=[saved]) == expected
    assert plan({"id": saved.id, "pruefsumme": checksum}, existing=[saved]) == expected


def test_a_trip_that_is_gone_is_an_error_not_a_new_trip() -> None:
    rows = rows_from_form(form({"start": "03.02.", "orte": "A → B", "km": "5", "id": "AAAAAAAAAA"}))
    with pytest.raises(TripTableError):
        plan_changes(rows, 2025, USER, [])


def test_km_are_summed_before_multiplying_and_exact_to_the_cent() -> None:
    assert km_amount(3, Decimal("0.30")) == Decimal("0.90")
    assert km_amount(7, Decimal("0.305")) == Decimal("2.14")  # halber Cent rundet auf


# --- Werte --------------------------------------------------------------------------------------


def test_fare_is_total_km_times_rate_with_items_per_trip() -> None:
    result = value(TRAVEL_FARE, [trip(3, 101), trip(10, 52, ("Altstadt", "Seehafen"))])

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount(Decimal("45.90"), Unit.EUR)  # 153 km * 0,30
    assert [i.amount for i in result.items] == [Amount.of(101, Unit.KM), Amount.of(52, Unit.KM)]
    assert any("153 km × 0,30 €/km" in s.text for s in result.workings.steps)


def test_without_trips_and_confirmation_the_fare_is_not_yet_computable() -> None:
    result = value(TRAVEL_FARE, [])
    assert isinstance(result, NotYetComputable) and "vollständig bestätigt" in result.reason


def test_confirmed_without_trips_is_an_explicit_zero() -> None:
    result = value(TRAVEL_FARE, [confirmation([])])
    assert isinstance(result, ExposedValue)
    assert result.amount == Amount(Decimal("0.00"), Unit.EUR)
    assert any("es gab keine" in s.text for s in result.workings.steps)


def test_total_is_the_sum_of_fare_lodging_and_incidentals_with_an_item_each() -> None:
    result = value(TRAVEL_TOTAL, [trip(3, 10)])

    assert isinstance(result, ExposedValue) and result.amount.value == Decimal("3.00")
    assert [i.label for i in result.items] == [
        "Fahrtkosten",
        "Übernachtungskosten",
        "Reisenebenkosten",
    ]
    assert isinstance(value(TRAVEL_TOTAL, []), NotYetComputable)


@pytest.mark.parametrize("key", [TRAVEL_LODGING, TRAVEL_INCIDENTALS])
def test_lodging_and_incidentals_are_zero_with_a_reason_once_there_is_a_fare(key: str) -> None:
    result = value(key, [trip(3, 10)])

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount(Decimal("0.00"), Unit.EUR)
    assert result.items == ()
    assert any("rechnet der Arbeitgeber ab" in s.text for s in result.workings.steps)


@pytest.mark.parametrize("key", [TRAVEL_LODGING, TRAVEL_INCIDENTALS])
def test_lodging_and_incidentals_follow_the_fare_when_it_is_not_computable(key: str) -> None:
    assert isinstance(value(key, []), NotYetComputable)
    confirmed = value(key, [confirmation([])])
    assert isinstance(confirmed, ExposedValue) and confirmed.amount.value == 0
    other = trip().model_copy(update={"year": 2030, "start": datetime.date(2030, 2, 3)})
    result = evaluate([WORK], [other]).get(key, USER, Period.year(2030))
    assert isinstance(result, NotYetComputable) and "km-Satz" in result.reason


def test_a_year_without_rate_is_not_yet_computable() -> None:
    other = trip().model_copy(update={"year": 2030, "start": datetime.date(2030, 2, 3)})
    result = evaluate([WORK], [other]).get(TRAVEL_FARE, USER, Period.year(2030))
    assert isinstance(result, NotYetComputable) and "km-Satz" in result.reason


def test_confirmation_ends_with_any_change_of_the_trips() -> None:
    first = trip(3, 10)
    sure = confirmation([first])
    assert current_confirmation([sure], [first]) == sure
    assert current_confirmation([sure], [first, trip(10, 5)]) is None
    assert current_confirmation([sure], [first.model_copy(update={"distance_km": 11})]) is None
    stale = evaluate([WORK], [first, sure, trip(10, 5)])
    assert any(f.kind == TRIPS_TO_FILL for f in stale.finding_list(USER, 2025).visible)


def test_finding_until_confirmed_then_none() -> None:
    def kinds(items: list[object]) -> list[str]:
        values = evaluate([WORK], items)  # type: ignore[arg-type]
        return [f.kind for f in values.finding_list(USER, 2025).visible]

    assert kinds([]) == [TRIPS_TO_FILL]
    assert kinds([trip()]) == [TRIPS_TO_FILL]
    assert kinds([trip(), confirmation([trip()])]) == [TRIPS_TO_FILL]  # anderer Stand
    only = trip()
    assert kinds([only, confirmation([only])]) == []


def test_anlage_n_fields_66_to_69_take_the_work_values() -> None:
    values = evaluate([WORK, TAX_YEAR], [trip(3, 101), trip(10, 52)])
    fare = values.get(N_TRAVEL_FARE, USER, YEAR)
    total = values.get(N_TRAVEL_TOTAL, USER, YEAR)

    assert isinstance(fare, ExposedValue) and fare.amount.value == Decimal("46")  # 45,90 gerundet
    assert isinstance(total, ExposedValue) and total.amount.value == Decimal("46")
    assert any("→" in s.text for s in fare.workings.steps)
    assert isinstance(evaluate([WORK, TAX_YEAR]).get(N_TRAVEL_FARE, USER, YEAR), NotYetComputable)


def test_anlage_n_fields_67_and_68_are_zero_with_a_reason_and_sum_into_69() -> None:
    values = evaluate([WORK, TAX_YEAR], [trip(3, 101), trip(10, 52)])

    for key in (N_TRAVEL_LODGING, N_TRAVEL_INCIDENTALS):
        result = values.get(key, USER, YEAR)
        assert isinstance(result, ExposedValue) and result.amount.value == 0
        assert any("rechnet der Arbeitgeber ab" in s for s in reasons_in_steps(result))
    total = values.get(N_TRAVEL_TOTAL, USER, YEAR)
    assert isinstance(total, ExposedValue) and total.amount.value == Decimal("46")
    assert isinstance(
        evaluate([WORK, TAX_YEAR]).get(N_TRAVEL_LODGING, USER, YEAR), NotYetComputable
    )


def reasons_in_steps(result: ExposedValue) -> list[str]:
    """Die Entscheidungen im Rechenweg, auch in den verwendeten Werten."""
    found = [s.text for s in result.workings.steps if s.kind == "decision"]
    for item in result.items:
        if item.locator.used_value is not None:
            found += reasons_in_steps(item.locator.used_value)
    return found


# --- Schreibweg ---------------------------------------------------------------------------------


def test_confirmation_is_checked_by_the_write_path(tmp_path: Path) -> None:
    store = open_store(tmp_path, WORK.kinds)
    saved = trip()
    assert isinstance(store.apply([Put(saved)]), Applied)
    wrong = confirmation([])  # Stand ohne die Reise
    rejected = store.apply([Put(wrong)])
    assert isinstance(rejected, Rejected)
    assert "geändert" in " ".join(rejected.reasons.values())
    right = confirmation([saved])
    assert isinstance(store.apply([Put(right)]), Applied)
    second = confirmation([saved])
    again = store.apply([Put(second)])
    assert isinstance(again, Rejected) and "schon eine Bestätigung" in " ".join(
        again.reasons.values()
    )


# --- Seite --------------------------------------------------------------------------------------


def make_client(root: Path, user: str = USER) -> httpx.Client:
    app = make_app(PORT, root, user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def stored(root: Path) -> dict[str, dict[str, object]]:
    path = root / "users" / USER / "work" / "2025.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def trips_in(root: Path) -> list[dict[str, object]]:
    return [e for key, e in stored(root).items() if key.startswith("BusinessTrip:")]


def hidden(page: str, name: str) -> str:
    found = re.search(rf'name="{name}" value="([^"]*)"', page)
    assert found
    return found.group(1)


NEW = {
    "zeilen": "2",
    "start-0": "03.02.2025",
    "ende-0": "04.02.",
    "orte-0": "Altstadt → Neudorf → Altstadt",
    "km-0": "101",
    "notiz-0": "Kunde",
    "start-1": "10.02.",
    "orte-1": "Altstadt -> Seehafen -> Altstadt",
    "km-1": "52",
}


def test_page_is_empty_prefilled_and_get_never_writes(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/arbeit?jahr=2025")
    assert response.status_code == 200
    assert "noch nicht berechenbar" in response.text
    assert "Verpflegung, Übernachtung und Nebenkosten rechnet der Arbeitgeber ab" in response.text
    assert "0,30 € je km" in response.text
    assert "<script>" not in response.text and 'src="/static/trip_table.js"' in response.text
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]  # nur der Nutzer


def test_the_old_trip_address_redirects_to_arbeit_with_the_year(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/arbeit/dienstreisen/2023")
    assert response.status_code == 308
    assert response.headers["location"] == "/arbeit?jahr=2023"
    assert client.get("/arbeit/dienstreisen/1800").status_code == 404


def test_saving_returns_to_arbeit_and_errors_show_the_whole_page(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    saved = client.post("/arbeit/dienstreisen/2024", data=post_data(2024), headers=ORIGIN)
    assert saved.status_code == 303 and saved.headers["location"] == "/arbeit?jahr=2024"
    bad = client.post("/arbeit/dienstreisen/2024", data=NEW | {"km-1": "abc"}, headers=ORIGIN)
    assert bad.status_code == 422
    assert "Erste Tätigkeitsstätte" in bad.text and "Arbeitsmittel" in bad.text
    assert "Lohnsteuerbescheinigung" in bad.text


def test_save_table_in_one_step_and_show_fare(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/arbeit/dienstreisen/2025", data=NEW, headers=ORIGIN)
    assert response.status_code == 303
    assert sorted(t["distance_km"] for t in trips_in(tmp_path)) == [52, 101]  # type: ignore[type-var]
    page = client.get("/arbeit?jahr=2025").text
    assert "45,90 €" in page and "153 km" in page and "Altstadt → Seehafen → Altstadt" in page
    assert "Altstadt → " in page  # Startort der letzten Reise vorbelegt
    assert "Noch nicht als vollständig bestätigt" in page


def test_invalid_cell_saves_nothing_and_keeps_input(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/arbeit/dienstreisen/2025", data=NEW | {"km-1": "abc"}, headers=ORIGIN)
    assert response.status_code == 422
    assert "Bitte die markierten Zellen korrigieren." in response.text
    assert 'value="abc"' in response.text and 'class="ungueltig"' in response.text
    assert [p.name for p in tmp_path.rglob("*.json")] == ["personal_details.json"]  # nur der Nutzer


def test_change_and_delete_with_the_shown_checksums(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/dienstreisen/2025", data=NEW, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    ids = re.findall(r'name="id-(\d)" value="([A-Z2-7]{10})"', page)
    sums = dict(re.findall(r'name="pruefsumme-(\d)" value="([0-9a-f]{64})"', page))
    assert len(ids) == 2  # die neue, leere Reise hat keine Kennung
    (n0, id0), (n1, id1) = ids
    data = {
        "zeilen": "3",
        f"id-{n0}": id0, f"pruefsumme-{n0}": sums[n0],
        f"start-{n0}": "2025-02-03", f"orte-{n0}": "A → B → A", f"km-{n0}": "110",
        f"id-{n1}": id1, f"pruefsumme-{n1}": sums[n1], f"loeschen-{n1}": "ja",
        f"start-{n1}": "2025-02-10", f"orte-{n1}": "A → B", f"km-{n1}": "52",
    }  # fmt: skip
    response = client.post("/arbeit/dienstreisen/2025", data=data, headers=ORIGIN)
    assert response.status_code == 303
    (left,) = trips_in(tmp_path)
    assert left["distance_km"] == 110 and left["id"] == id0


def test_stale_table_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/arbeit/dienstreisen/2025",
        data={k: v for k, v in NEW.items() if not k.endswith("-1")} | {"zeilen": "1"},
        headers=ORIGIN,
    )
    page = client.get("/arbeit?jahr=2025").text
    entry_id, checksum = hidden(page, "id-0"), hidden(page, "pruefsumme-0")
    row = {
        "zeilen": "1", "id-0": entry_id, "pruefsumme-0": checksum,
        "start-0": "2025-02-03", "orte-0": "A → B → A",
    }  # fmt: skip
    assert (
        client.post(
            "/arbeit/dienstreisen/2025", data=row | {"km-0": "5"}, headers=ORIGIN
        ).status_code
        == 303
    )
    stale = client.post("/arbeit/dienstreisen/2025", data=row | {"km-0": "6"}, headers=ORIGIN)
    assert stale.status_code == 409 and "Inzwischen geändert" in stale.text
    assert trips_in(tmp_path)[0]["distance_km"] == 5


def test_confirm_withdraw_and_any_change_ends_the_confirmation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/dienstreisen/2025", data=NEW, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    stand = hidden(page, "stand")
    done = client.post(
        "/arbeit/dienstreisen/2025/vollstaendig", data={"stand": stand}, headers=ORIGIN
    )
    assert done.status_code == 303
    page = client.get("/arbeit?jahr=2025").text
    assert "Vollständig bestätigt am" in page
    findings = client.get("/befunde?year=2025").text
    assert "Dienstreisen 2025 noch auszufüllen" not in findings

    # Bestätigung aufheben
    assert (
        client.post("/arbeit/dienstreisen/2025/vollstaendig/aufheben", headers=ORIGIN).status_code
        == 303
    )
    assert "Noch nicht als vollständig bestätigt" in client.get("/arbeit?jahr=2025").text
    assert "Dienstreisen 2025 noch auszufüllen" in client.get("/befunde?year=2025").text

    # erneut bestätigen, dann eine Reise ändern: Bestätigung gilt nicht mehr
    stand = hidden(client.get("/arbeit?jahr=2025").text, "stand")
    client.post("/arbeit/dienstreisen/2025/vollstaendig", data={"stand": stand}, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    row = {
        "zeilen": "1", "id-0": hidden(page, "id-0"), "pruefsumme-0": hidden(page, "pruefsumme-0"),
        "start-0": "2025-02-03", "orte-0": "A → B → A", "km-0": "9",
    }  # fmt: skip
    client.post("/arbeit/dienstreisen/2025", data=row, headers=ORIGIN)
    assert "Noch nicht als vollständig bestätigt" in client.get("/arbeit?jahr=2025").text


def test_confirming_an_unseen_state_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    stand = hidden(client.get("/arbeit?jahr=2025").text, "stand")
    client.post("/arbeit/dienstreisen/2025", data=NEW, headers=ORIGIN)
    response = client.post(
        "/arbeit/dienstreisen/2025/vollstaendig", data={"stand": stand}, headers=ORIGIN
    )
    assert response.status_code == 409 and "inzwischen geändert" in response.text
    assert not any(k.startswith("TripsConfirmation:") for k in stored(tmp_path))


def test_confirming_with_no_trips_gives_an_explicit_zero(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    stand = hidden(client.get("/arbeit?jahr=2025").text, "stand")
    client.post("/arbeit/dienstreisen/2025/vollstaendig", data={"stand": stand}, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    assert "Vollständig bestätigt am" in page and "0,00 €" in page


def test_trips_of_another_user_and_other_origins(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/arbeit/dienstreisen/2025", data=NEW, headers=ORIGIN)
    ben = make_client(tmp_path, "ben")
    assert "Altstadt" not in ben.get("/arbeit?jahr=2025").text
    assert client.post("/arbeit/dienstreisen/2025", data=NEW).status_code == 403


def test_text_is_escaped(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = {"zeilen": "1", "start-0": "03.02.", "orte-0": "<b>A</b> → B", "km-0": "5"}
    client.post("/arbeit/dienstreisen/2025", data=data, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    assert "<b>A</b>" not in page and "&lt;b&gt;A&lt;/b&gt;" in page


# --- Dienstreisetage (Anlage N Nr. 28) ----------------------------------------------------------


def test_trip_days_count_each_trip_from_start_to_end_inclusive() -> None:
    long = trip(day=3).model_copy(update={"end": datetime.date(2025, 2, 5)})
    result = value("work.trip_days", [long, trip(day=10)])

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.of(4, Unit.DAYS)  # 3 Tage + 1 Tag (ohne Ende)


def test_trip_days_without_trips_need_the_confirmation() -> None:
    assert isinstance(value("work.trip_days", []), NotYetComputable)

    result = value("work.trip_days", [confirmation([])])

    assert isinstance(result, ExposedValue) and result.amount == Amount.of(0, Unit.DAYS)


def post_data(year: int) -> dict[str, str]:
    return {"zeilen": "1", "start-0": f"03.02.{year}", "orte-0": "A → B → A", "km-0": "9"}


def post_trip(client: httpx.Client, year: int) -> None:
    client.post(f"/arbeit/dienstreisen/{year}", data=post_data(year), headers=ORIGIN)


def header_years(page: str) -> list[int]:
    select = page.split('<select name="year"', 1)[1].split(">", 1)[1].split("</select>", 1)[0]
    return [int(y) for y in re.findall(r'<option value="(\d+)"', select)]


def test_arbeit_shows_one_year_chosen_in_the_header(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/arbeit").text
    assert '<nav class="liste"' not in page  # keine eigene Jahresleiste mehr
    assert "Dienstreisen 2025" in page
    assert '<form method="post" action="/arbeit/dienstreisen/2025"' in page
    assert "<script>" not in page and " style=" not in page
    post_trip(client, 2023)
    chosen = client.get("/arbeit?jahr=2023").text
    assert "Dienstreisen 2023" in chosen and 'action="/arbeit/dienstreisen/2023"' in chosen
    assert "Dienstreisen 2025" not in chosen
    assert '<option value="2023" selected>' in chosen  # die Kopfleiste zeigt das Jahr der Seite
    assert "Dienstreisen 2025" in client.get("/arbeit?jahr=abc").text


def test_header_offers_the_years_of_entries_newest_ten(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    for year in range(2010, 2022):
        post_trip(client, year)
    assert header_years(client.get("/arbeit").text) == [2025, *range(2021, 2012, -1)]


def test_finding_links_to_the_work_page_of_its_year() -> None:
    (found,) = evaluate([WORK], []).finding_list(USER, 2024).visible

    assert found.kind == TRIPS_TO_FILL
    assert found.href == "/arbeit?jahr=2024#dienstreisen"  # direkt auf die Tabelle der Dienstreisen


def test_not_computable_reason_is_a_focusable_tooltip(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    text = client.get("/arbeit?jahr=2025").text
    assert 'class="kurzinfo" tabindex="0" title="' in text
    assert "</strong> (" not in text  # kein Klammertext hinter „noch nicht berechenbar“


KEY_PATTERN = re.compile(r"\b[a-z][a-z_]*\.[a-z][a-z_]*\b")


def reasons_of(page: str) -> list[str]:
    """Alle Begründungen der Seite: Kurzinfo-Titel und deren Folgetext."""
    titles = re.findall(r'class="kurzinfo"[^>]*title="([^"]*)"', page)
    return [html.unescape(t) for t in titles]


@pytest.mark.parametrize(
    "path",
    [
        "/arbeit?jahr=2025",
        "/steuerjahr",
        "/steuerjahr/anlage-n/2025",
        "/steuerjahr/anlage-vor/2025",
    ],
)
def test_reasons_on_the_pages_name_no_internal_value_keys(tmp_path: Path, path: str) -> None:
    page = make_client(tmp_path).get(path)
    assert page.status_code == 200
    assert reasons_of(page.text) or path != "/arbeit?jahr=2025"
    for reason in reasons_of(page.text):
        assert not KEY_PATTERN.search(reason), reason


def test_not_applicable_reason_is_a_focusable_tooltip(tmp_path: Path) -> None:
    env = make_app(PORT, tmp_path, user=USER).state.templates.env
    result = NotApplicable(ValueKey("work.demo"), USER, Period.year(2025), None, "abgeschaltet")

    text = env.from_string(
        '{% from "_value.html" import value_view %}{{ value_view("Titel", result) }}'
    ).render(result=result)

    assert 'class="kurzinfo" tabindex="0" title="abgeschaltet"' in text
    assert ">entfällt</strong>" in text
    assert "entfällt</strong> (" not in text


def chain_titles_of(page: str) -> list[str]:
    """Alle Einträge der aufklappbaren Rechenwege (Kette) der Seite."""
    lists = re.findall(r'<ol class="kette">(.*?)</ol>', page, re.S)
    return [html.unescape(t) for ol in lists for t in re.findall(r"<li>(.*?)</li>", ol)]


@pytest.mark.parametrize(
    "path", ["/arbeit?jahr=2025", "/steuerjahr/anlage-n/2025", "/steuerjahr/anlage-vor/2025"]
)
def test_chain_shows_short_titles_and_opens_with_the_calculator_symbol(
    tmp_path: Path, path: str
) -> None:
    page = make_client(tmp_path).get(path).text

    titles = chain_titles_of(page)
    assert titles or path != "/steuerjahr/anlage-n/2025"
    for title in titles:
        assert not KEY_PATTERN.search(title), title
    summaries = re.findall(r'<summary class="rechenweg-symbol"[^>]*>.*?</summary>', page, re.S)
    assert len(summaries) == page.count('<ol class="kette">')
    for summary in summaries:
        assert 'title="Rechenweg" aria-label="Rechenweg"' in summary
        assert "<svg" in summary and "Rechenweg</span>" in summary
    assert "<summary>Kette</summary>" not in page


def test_chain_titles_are_catalog_titles(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/steuerjahr/anlage-n/2025").text

    assert "Einbehaltene Lohnsteuer" in chain_titles_of(page)


# --- Tabelle der Reisekosten und Fußzeile der Dienstreisen --------------------------------------


def costs_table(page: str) -> str:
    return page.split('class="reisekosten"', 1)[1].split("</table>", 1)[0]


def test_arbeit_shows_the_travel_costs_as_a_small_table_without_expanding(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    post_trip(client, 2025)
    page = client.get("/arbeit?jahr=2025").text

    assert '<span class="titel">Fahrtkosten:' not in page  # kein aufklappbarer Wert mehr
    assert '<span class="titel">Summe der Reisekosten:' not in page
    assert "<summary>" not in costs_table(page)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", costs_table(page), re.S)
    first_cells = [" ".join(re.sub(r"<[^>]+>", " ", r.split("</td>")[0]).split()) for r in rows[1:]]
    wanted = ["Fahrtkosten", "Übernachtungskosten", "Reisenebenkosten", "Summe der Reisekosten"]
    assert (
        all(c.startswith(w) for c, w in zip(first_cells, wanted, strict=False))
        and len(first_cells) == 4
    )
    table = costs_table(page)
    assert table.count("rechnet der Arbeitgeber ab") == 2
    assert 'href="#dienstreisen"' in table  # Fahrtkosten führt auf die Tabelle
    assert "Angenommen" in table or "angenommen" in table
    assert "2,70" in table


def test_travel_costs_show_the_reason_instead_of_an_amount(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    table = costs_table(client.get("/arbeit?jahr=2025").text)

    assert table.count('<strong class="fehler">noch nicht berechenbar') == 4
    assert "vollständig bestätigt" in table


def test_trip_table_has_no_backing_column_and_a_compact_footer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = post_data(2025) | {
        "zeilen": "2",
        "start-1": "10.02.2025",
        "ende-1": "11.02.2025",
        "orte-1": "A → C → A",
        "km-1": "21",
    }
    client.post("/arbeit/dienstreisen/2025", data=data, headers=ORIGIN)
    page = client.get("/arbeit?jahr=2025").text
    form = page.split('id="dienstreisen"', 1)[1].split("</form>", 1)[0]

    assert "<th>Belegstand" not in form
    footer = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", form.split("<tfoot>", 1)[1]))
    assert "Summe 2 Dienstreisen · 3 Tage · 30 km × 0,30 €/km = 9,00 €" in footer
    assert "angenommen" in footer.lower()


def test_trip_footer_shows_the_reason_without_a_rate_or_confirmation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    form = client.get("/arbeit?jahr=2025").text.split('id="dienstreisen"', 1)[1]
    footer = form.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    assert "noch nicht berechenbar" in footer and "0,00" not in footer

    post_trip(client, 2030)  # für 2030 gibt es keinen km-Satz
    form = client.get("/arbeit?jahr=2030").text.split('id="dienstreisen"', 1)[1]
    footer = form.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    assert "noch nicht berechenbar" in footer and "km-Satz" in footer

    client.post(
        "/arbeit/dienstreisen/2025/vollstaendig",
        data={"stand": hidden(client.get("/arbeit?jahr=2025").text, "stand")},
        headers=ORIGIN,
    )
    form = client.get("/arbeit?jahr=2025").text.split('id="dienstreisen"', 1)[1]
    footer = form.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    assert "Summe 0 Dienstreisen" in footer and "0,00 €" in footer


# --- Anker und Adresse einer Reise --------------------------------------------------------------


def test_every_saved_trip_has_an_anchor_and_an_address_that_leads_to_it(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    post_trip(client, 2025)
    (saved,) = trips_in(tmp_path)
    trip_id = str(saved["id"])
    page = client.get("/arbeit?jahr=2025").text

    assert f'id="reise-{trip_id}"' in page
    assert 'id="dienstreisen"' in page
    link = client.get(f"/arbeit/dienstreisen/reise/{trip_id}")
    assert link.status_code == 303
    assert link.headers["location"] == f"/arbeit?jahr=2025#reise-{trip_id}"
    assert client.get("/arbeit/dienstreisen/reise/UNBEKANNT0").status_code == 404

    address = EntryAddress(kind="BusinessTrip", id=trip_id)
    assert WORK.entry_url(address) == f"/arbeit/dienstreisen/reise/{trip_id}"


def test_the_item_of_a_trip_under_nr_66_links_to_its_row(
    tmp_path: Path, anlage_n_text: Callable[[httpx.Client], str]
) -> None:
    client = make_client(tmp_path)
    post_trip(client, 2025)
    (saved,) = trips_in(tmp_path)
    page = anlage_n_text(client)

    assert f'href="/arbeit/dienstreisen/reise/{saved["id"]}"' in page
