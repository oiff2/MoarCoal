"""Tests: Karte der Dienstreisen mit Ortssuche auf Klick (#114).

Nur erfundene Orte; die Ortssuche ist immer ein Fake, nichts berührt das Netz; geschrieben wird
nur in `tmp_path`.
"""

import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from moarcoal.app import create_app
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import BusinessTrip
from moarcoal.modules.work.germany_map import germany_map
from moarcoal.modules.work.places import (
    Place,
    PlaceError,
    PlaceUse,
    check_place,
    forget_changes,
    hide_changes,
    locate_changes,
    place_uses,
    sort_places,
)
from moarcoal.place_search import (
    MIN_INTERVAL_SECONDS,
    USER_AGENT,
    FakePlaceSearch,
    NominatimSearch,
    PlaceHit,
    PlaceSearchError,
)
from moarcoal.storage import Put, Store, entry_checksum

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
USER = "anna"
YEAR = 2025
NODE = f"/arbeit/dienstreisen/{YEAR}"
MUSTERSTADT = PlaceHit("Musterstadt, Beispielkreis, Bayern, Deutschland", "Bayern", 48.5, 11.5)
SPAIN = PlaceHit("Madrid, Spanien", "", 40.4, -3.7)


def trip(day: int, *places: str) -> BusinessTrip:
    return BusinessTrip(
        owner=USER,
        year=YEAR,
        start=datetime.date(YEAR, 3, day),
        places=places,
        distance_km=50,
    )


# --- Fachkern ------------------------------------------------------------------------------------


def test_a_written_back_startort_is_no_reiseziel_and_each_trip_counts_once() -> None:
    uses = place_uses(
        [
            trip(1, "Heimstadt", "Messeort", "Heimstadt"),
            trip(2, "Heimstadt", "Messeort", "Kundendorf", "Messeort", "Heimstadt"),
            trip(3, "Heimstadt", "Kundendorf"),
        ]
    )
    assert uses == [
        PlaceUse("Heimstadt", True, 0),
        PlaceUse("Kundendorf", False, 2),
        PlaceUse("Messeort", False, 2),
    ]


def test_an_ort_can_be_startort_and_reiseziel_and_goals_sort_by_trips_then_name() -> None:
    uses = place_uses(
        [trip(1, "Altstadt", "Neustadt"), trip(2, "Neustadt", "B"), trip(3, "Neustadt", "A")]
    )
    assert uses == [
        PlaceUse("Altstadt", True, 0),
        PlaceUse("Neustadt", True, 1),
        PlaceUse("A", False, 1),
        PlaceUse("B", False, 1),
    ]


def test_orte_are_sorted_into_map_unplaced_and_not_shown() -> None:
    germany = germany_map()
    places = [
        Place(owner=USER, name="Heimstadt", latitude=48.5, longitude=11.5),
        Place(owner=USER, name="Wien", hidden=True),
        Place(owner=USER, name="Fernweh", latitude=40.0, longitude=-3.7),  # nach der Karte gewählt
    ]
    uses = [PlaceUse(n, n == "Heimstadt", 1) for n in ("Heimstadt", "Wien", "MS", "Fernweh")]
    sorted_places = sort_places(uses, places, germany)
    assert [p.use.name for p in sorted_places.points] == ["Heimstadt"]
    assert [u.name for u in sorted_places.hidden] == ["Wien"]
    assert [u.name for u in sorted_places.unplaced] == ["MS", "Fernweh"]
    assert sorted_places.points[0].tooltip == "Heimstadt · Startort · 1 Fahrt"


def test_the_projection_puts_north_up_and_east_right_and_none_outside() -> None:
    germany = germany_map()
    north, south = germany.project(54.0, 10.0), germany.project(48.0, 10.0)
    west, east = germany.project(51.0, 7.0), germany.project(51.0, 13.0)
    assert north and south and west and east
    assert north[1] < south[1] and west[0] < east[0]
    assert germany.project(40.0, 10.0) is None and germany.project(51.0, 25.0) is None
    assert germany.outline.startswith("M") and germany.borders.startswith("M")


@pytest.mark.parametrize(
    "bad",
    [
        {"latitude": 48.5},  # Breite ohne Länge
        {"latitude": 48.5, "longitude": 11.5, "hidden": True},  # beides
        {},  # keines von beiden
        {"latitude": 99.0, "longitude": 11.5},
        {"name": " " * 0},
    ],
)
def test_a_place_has_a_position_or_is_hidden_never_both(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Place(**({"owner": USER, "name": "MS"} | bad))  # pyright: ignore[reportArgumentType]


def test_locate_hide_forget_replace_the_one_place_and_check_its_version() -> None:
    germany = germany_map()
    (put,) = locate_changes(USER, "MS", None, 48.5, 11.5, "Musterstadt", germany)
    assert isinstance(put, Put) and put.expected is None
    stored = put.entry
    assert isinstance(stored, Place)
    (hide,) = hide_changes(USER, "MS", stored)
    assert isinstance(hide, Put) and isinstance(hide.entry, Place)
    assert (
        hide.entry.id == stored.id and hide.entry.hidden and hide.expected == entry_checksum(stored)
    )
    (gone,) = forget_changes(stored)
    assert gone.address == stored.address
    assert forget_changes(None) == []
    with pytest.raises(PlaceError):
        locate_changes(USER, "MS", None, 40.0, -3.7, "Madrid", germany)


def test_only_one_place_per_name_and_user() -> None:
    first = Place(owner=USER, name="MS", hidden=True)
    second = Place(owner=USER, name="MS", latitude=48.5, longitude=11.5)
    other = Place(owner="ben", name="MS", hidden=True)
    entries = {e.address: e for e in (first, second, other)}
    assert check_place(first, entries) is not None
    assert check_place(other, entries) is None


# --- Die Suche: der eine Aufrufbaustein, ohne Netz -----------------------------------------------

ANSWER = json.dumps(
    [
        {
            "display_name": "Musterstadt, Bayern, Deutschland",
            "lat": "48.5",
            "lon": "11.5",
            "address": {"state": "Bayern"},
        }
    ]
).encode()


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_the_search_sends_only_the_text_to_germany_with_a_generic_agent() -> None:
    requests: list[urllib.request.Request] = []

    def fetch(request: urllib.request.Request) -> bytes:
        requests.append(request)
        return ANSWER

    clock = Clock()
    search = NominatimSearch(fetch, lambda: clock.now, clock.sleep)
    assert search.search("Musterstadt") == [
        PlaceHit("Musterstadt, Bayern, Deutschland", "Bayern", 48.5, 11.5)
    ]
    (request,) = requests
    assert request.full_url.startswith("https://nominatim.openstreetmap.org/search?q=Musterstadt&")
    assert "countrycodes=de" in request.full_url
    assert request.get_header("User-agent") == USER_AGENT
    assert "@" not in USER_AGENT


def test_requests_are_at_least_a_second_apart() -> None:
    clock = Clock()
    search = NominatimSearch(lambda _: ANSWER, lambda: clock.now, clock.sleep)
    search.search("a")
    search.search("b")
    assert clock.slept == [pytest.approx(MIN_INTERVAL_SECONDS)]  # pyright: ignore[reportUnknownMemberType]


def test_offline_and_garbage_answers_become_a_message() -> None:
    def offline(_: urllib.request.Request) -> bytes:
        raise urllib.error.URLError("offline")

    with pytest.raises(PlaceSearchError, match="nicht erreichbar: offline"):
        NominatimSearch(offline).search("x")
    with pytest.raises(PlaceSearchError, match="nicht lesbar"):
        NominatimSearch(lambda _: b"<html>").search("x")
    with pytest.raises(PlaceSearchError, match="nicht lesbar"):
        NominatimSearch(lambda _: b'[{"lat": "1"}]').search("x")


# --- Seite ---------------------------------------------------------------------------------------


class Setup:
    def __init__(self, root: Path, search: FakePlaceSearch) -> None:
        self.root = root / "data"
        self.search = search
        self.app = create_app(PORT, self.root, [WORK], user=USER, place_search=search)
        self.client: httpx.Client = TestClient(
            self.app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False
        )
        self.store.apply(
            [
                Put(trip(1, "MS", "Probenburg", "MS")),
                Put(trip(2, "MS", "Probenburg", "Testfurt", "MS")),
                Put(trip(3, "MS", "Wien")),
            ]
        )

    @property
    def store(self) -> Store:
        return self.app.state.store

    def post(self, action: str, **data: str) -> httpx.Response:
        return self.client.post(f"{NODE}/orte/{action}", data=data, headers=ORIGIN)

    def pick(self, ort: str = "MS", hit: PlaceHit = MUSTERSTADT, **extra: str) -> httpx.Response:
        data = {
            "ort": ort,
            "breite": str(hit.latitude),
            "laenge": str(hit.longitude),
            "name": hit.name,
        }
        return self.post("lage", **(data | extra))

    def page(self) -> str:
        return self.client.get(NODE).text

    def places(self) -> list[Place]:
        return self.store.state().of_kind(Place)


@pytest.fixture
def search() -> FakePlaceSearch:
    return FakePlaceSearch([MUSTERSTADT])


@pytest.fixture
def setup(tmp_path: Path, search: FakePlaceSearch) -> Setup:
    return Setup(tmp_path, search)


def test_orte_without_a_position_are_listed_with_a_prefilled_search_field(setup: Setup) -> None:
    html = setup.page()
    assert 'id="ohne-lage"' in html and "Ohne Lage (4)" in html
    assert '<input name="suche" value="MS"' in html
    assert '<input name="suche" value="Probenburg"' in html
    assert "0 Orte auf der Karte, 4 ohne Lage" in html
    assert setup.search.asked == []  # the page alone never asks


def test_a_search_sends_only_the_typed_text_and_lists_hits_without_storing(
    setup: Setup,
) -> None:
    html = setup.post("suche", ort="MS", suche="Musterstadt").text
    assert setup.search.asked == ["Musterstadt"]
    assert "Musterstadt, Beispielkreis, Bayern, Deutschland · Bayern" in html
    assert 'name="breite" value="48.5"' in html
    assert setup.places() == []


def test_get_never_searches_or_writes(setup: Setup) -> None:
    setup.page()
    assert setup.search.asked == [] and setup.places() == []


def test_picking_a_hit_stores_the_place_once_for_all_years(setup: Setup) -> None:
    response = setup.pick()
    assert response.status_code == 303
    (place,) = setup.places()
    assert (place.name, place.latitude, place.longitude, place.found_as) == (
        "MS",
        48.5,
        11.5,
        MUSTERSTADT.name,
    )
    stored = list((setup.root / "users" / USER / "work").glob("places.json"))
    assert len(stored) == 1
    html = setup.page()
    assert '<g class="pt"' in html and "<title>MS · Startort</title>" in html
    assert "1 Ort auf der Karte, 3 ohne Lage" in html
    assert '<input name="suche" value="MS"' not in html
    # another year has other trips but would use the same stored position
    other = setup.client.get("/arbeit/dienstreisen/2024").text
    assert "0 Orte auf der Karte" in other


def test_the_map_marks_startort_and_reiseziele_not_by_colour_alone(setup: Setup) -> None:
    for ort in ("MS", "Probenburg", "Testfurt"):
        setup.pick(ort)
    html = setup.page()
    assert "<title>MS · Startort</title>" in html  # written back twice, still no Reiseziel
    assert "<title>Probenburg · 2 Fahrten</title>" in html
    assert "<title>Testfurt · 1 Fahrt</title>" in html
    assert '<path class="marke start"' in html and '<circle class="marke ziel"' in html
    assert ">S</text>" in html and ">2</text>" in html and ">Probenburg</text>" in html


def test_a_network_error_and_no_hit_and_empty_text_show_a_message_and_store_nothing(
    tmp_path: Path,
) -> None:
    failing = Setup(tmp_path, FakePlaceSearch(error="Die Ortssuche ist nicht erreichbar: offline"))
    response = failing.post("suche", ort="MS", suche="MS")
    assert response.status_code == 502
    assert "Die Ortssuche ist nicht erreichbar: offline" in response.text
    assert '<input name="suche" value="MS"' in response.text and failing.places() == []

    empty = Setup(tmp_path / "zwei", FakePlaceSearch())
    assert "Kein Treffer in Deutschland für „Nirgendwo“." in (
        empty.post("suche", ort="MS", suche="Nirgendwo").text
    )
    empty.search.asked.clear()
    blank = empty.post("suche", ort="MS", suche=" ")
    assert blank.status_code == 422 and "Bitte einen Suchbegriff eingeben." in blank.text
    assert empty.search.asked == []


def test_only_orte_of_the_year_get_a_position_and_it_must_lie_on_the_map(setup: Setup) -> None:
    assert setup.pick("Fremdort").status_code == 404
    assert setup.post("suche", ort="Fremdort", suche="x").status_code == 404
    assert setup.search.asked == []
    assert setup.pick(hit=SPAIN).status_code == 400
    assert setup.pick(breite="abc").status_code == 400
    assert setup.pick(breite="nan").status_code == 400
    assert setup.places() == []


def test_a_foreign_origin_cannot_search_or_write(setup: Setup) -> None:
    response = setup.client.post(
        f"{NODE}/orte/suche",
        data={"ort": "MS", "suche": "x"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403 and setup.search.asked == []


def test_an_ort_can_be_hidden_forgotten_and_a_position_taken_back(setup: Setup) -> None:
    assert setup.post("ausblenden", ort="Wien").status_code == 303
    (place,) = setup.places()
    assert place.hidden and place.name == "Wien"
    html = setup.page()
    assert "Ohne Lage (3)" in html and '<input name="suche" value="Wien"' not in html
    assert "Nicht auf der Karte gezeigt (1)" in html

    setup.post("vergessen", ort="Wien")
    assert setup.places() == [] and '<input name="suche" value="Wien"' in setup.page()

    setup.pick()
    setup.post("vergessen", ort="MS")
    assert setup.places() == []
    assert setup.post("vergessen", ort="MS").status_code == 303  # nothing left: no error


def test_a_hidden_ort_can_get_a_position_later(setup: Setup) -> None:
    setup.post("ausblenden", ort="MS")
    setup.pick()
    (place,) = setup.places()
    assert not place.hidden and place.latitude == 48.5


def test_the_page_has_no_external_address(setup: Setup) -> None:
    setup.pick()
    html = setup.page()
    assert "http://" not in html and "https://" not in html
    assert 'style="' not in html
