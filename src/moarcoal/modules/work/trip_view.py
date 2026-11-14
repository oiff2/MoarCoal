"""Der Inhalt der Dienstreiseseite eines Jahrs, geteilt von `/arbeit` und der Jahresadresse."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.links import document_url
from moarcoal.modules.work.entries import (
    MODULE_KEY,
    BusinessTrip,
    TripsConfirmation,
    trips_fingerprint,
)
from moarcoal.modules.work.germany_map import germany_map
from moarcoal.modules.work.places import Place, place_uses, sort_places
from moarcoal.modules.work.trip_reading import IGNORED, proposed_trips, statements
from moarcoal.modules.work.trips import (
    KM_RATES,
    TripRow,
    current_confirmation,
    place_prefill,
    sorted_trips,
)
from moarcoal.modules.work.values import TRAVEL_FARE, TRAVEL_TOTAL
from moarcoal.place_search import PlaceHit
from moarcoal.proposals import proposals_of
from moarcoal.storage import entry_checksum
from moarcoal.values.model import Period
from moarcoal.web import module_state, store_of, user_of, values_of, year_of

MAX_YEARS = 10  # so viele Jahre stehen höchstens zur Auswahl


@dataclass(frozen=True)
class PlaceSearchView:
    """Ergebnis einer Ortssuche auf Klick, nur zum Anzeigen: nichts davon ist gespeichert."""

    place: str
    text: str
    hits: list[PlaceHit]
    message: str = ""


def trips_of(request: Request, year: int) -> list[BusinessTrip]:
    state = module_state(request, MODULE_KEY)
    return sorted_trips([t for t in state.all(BusinessTrip) if t.year == year])


def places_of(request: Request) -> list[Place]:
    return module_state(request, MODULE_KEY).all(Place)


def confirmations_of(request: Request, year: int) -> list[TripsConfirmation]:
    state = module_state(request, MODULE_KEY)
    return [c for c in state.all(TripsConfirmation) if c.year == year]


def trip_years(request: Request) -> list[int]:
    """Jahre zur Auswahl: Jahre mit Dienstreisen und das aktuelle Steuerjahr, neueste zuerst."""
    state = module_state(request, MODULE_KEY)
    found = {DEFAULT_YEAR, *(t.year for t in state.all(BusinessTrip))}
    return sorted(found, reverse=True)[:MAX_YEARS]


def chosen_year(request: Request, years: Sequence[int]) -> int:
    """Das Jahr aus `?jahr=`, sonst das neueste; Unbrauchbares zählt als nicht gewählt."""
    year = year_of(request.query_params.get("jahr", ""), in_range=True)
    return years[0] if year is None else year


def _statements(request: Request, year: int, trips: Sequence[BusinessTrip]) -> list[dict[str, Any]]:
    """Je Reiseaufstellung des Jahrs ihr neuester Vorschlag als Tabelle (oder noch keiner)."""
    state = module_state(request, MODULE_KEY)
    found: list[dict[str, Any]] = []
    for document in statements(state.documents(), year):
        history = proposals_of(store_of(request).state(), document)
        proposal = history[-1] if history else None
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
        "trip_years": trip_years(request),
        "year": year,
        "rows": rows,
        "error": error,
        "trip_count": len(trips),
        "total_km": sum(t.distance_km for t in trips),
        "rate": rate,
        "confirmation": current_confirmation(confirmations_of(request, year), trips),
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
