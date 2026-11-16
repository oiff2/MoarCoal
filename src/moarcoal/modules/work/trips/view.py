"""Der Inhalt der Dienstreiseseite eines Jahrs, geteilt von `/arbeit` und der Jahresadresse."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from moarcoal.defaults import year_of
from moarcoal.modules.work.common import MODULE_KEY
from moarcoal.modules.work.trips.entries import BusinessTrip, trips_fingerprint
from moarcoal.modules.work.trips.germany_map import germany_map
from moarcoal.modules.work.trips.place_search import PlaceHit
from moarcoal.modules.work.trips.places import Place, place_uses, sort_places
from moarcoal.modules.work.trips.reading import IGNORED, proposed_trips, statements
from moarcoal.modules.work.trips.table import (
    KM_RATES,
    TripRow,
    confirmation_in,
    place_prefill,
    trips_in,
)
from moarcoal.modules.work.trips.values import TRAVEL_FARE, TRAVEL_TOTAL
from moarcoal.storage import entry_checksum
from moarcoal.values.model import Period
from moarcoal.web.helpers import (
    global_year,
    module_state,
    user_of,
    values_of,
    year_choices,
)
from moarcoal.web.links import document_url


@dataclass(frozen=True)
class PlaceSearchView:
    """Ergebnis einer Ortssuche auf Klick, nur zum Anzeigen: nichts davon ist gespeichert."""

    place: str
    text: str
    hits: list[PlaceHit]
    message: str = ""


def trips_of(request: Request, year: int) -> list[BusinessTrip]:
    return trips_in(module_state(request, MODULE_KEY), year)


def places_of(request: Request) -> list[Place]:
    return module_state(request, MODULE_KEY).all(Place)


def trip_years(request: Request, chosen: int) -> list[int]:
    """Jahre zur Auswahl: Jahre mit Dienstreisen und das aktuelle Steuerjahr, neueste zuerst.
    Ein gewähltes Jahr außerhalb der Liste steht zusätzlich an seinem Platz."""
    found = {t.year for t in module_state(request, MODULE_KEY).all(BusinessTrip)}
    return year_choices(found, chosen)


def chosen_year(request: Request) -> int:
    """Das Jahr aus `?jahr=`, sonst das globale Jahr; Unbrauchbares zählt als nicht gewählt."""
    year = year_of(request.query_params.get("jahr", ""), in_range=True)
    return global_year(request) if year is None else year


def _statements(request: Request, year: int, trips: Sequence[BusinessTrip]) -> list[dict[str, Any]]:
    """Je Reiseaufstellung des Jahrs ihr neuester Vorschlag als Tabelle (oder noch keiner)."""
    state = module_state(request, MODULE_KEY)
    found: list[dict[str, Any]] = []
    for document in statements(state.documents(), year):
        proposal = state.latest_proposal(document)
        found.append(
            {
                "document": document,
                "url": document_url(document.id),
                "proposal": proposal,
                "checksum": entry_checksum(proposal) if proposal else "",
                "trips": [] if proposal is None else proposed_trips(proposal, year, trips),
                "ignored": None if proposal is None else proposal.fields.get(IGNORED),
            }
        )
    return found


def trips_context(
    request: Request,
    year: int,
    *,
    rows: list[TripRow] | None = None,
    error: str = "",
    problems: dict[int, str] | None = None,
    search: PlaceSearchView | None = None,
) -> dict[str, Any]:
    """Die Vorlagenwerte der Dienstreiseseite (`work/_trips.html`) samt Jahresauswahl."""
    trips = trips_of(request, year)
    rate = KM_RATES.get(year)
    if rows is None:
        rows = [TripRow.from_trip(t, rate) for t in trips]
        rows.append(TripRow(places=place_prefill(trips)))
    period = Period.year(year)
    values = values_of(request)
    user = user_of(request)
    return {
        "trip_years": trip_years(request, year),
        "year": year,
        "rows": rows,
        "error": error,
        "trip_count": len(trips),
        "total_km": sum(t.distance_km for t in trips),
        "rate": rate,
        "confirmation": confirmation_in(module_state(request, MODULE_KEY), year),
        "stand": trips_fingerprint(trips),
        "fare": values.get(TRAVEL_FARE, user, period),
        "total": values.get(TRAVEL_TOTAL, user, period),
        "statements": _statements(request, year, trips),
        "germany": germany_map(),
        "map_places": sort_places(place_uses(trips), places_of(request), germany_map()),
        "search": search,
        "problems": problems or {},
        "min_date": f"{year}-01-01",
        "max_date": f"{year}-12-31",
    }
