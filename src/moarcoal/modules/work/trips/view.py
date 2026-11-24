"""Der Inhalt der Dienstreisen eines Jahrs auf der Seite Arbeit."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import Request

from moarcoal.defaults import year_of
from moarcoal.modules.work.common import MODULE_KEY, TRIPS_ANCHOR, trip_anchor
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
from moarcoal.modules.work.trips.values import (
    TRAVEL_FARE,
    TRAVEL_INCIDENTALS,
    TRAVEL_LODGING,
    TRAVEL_TOTAL,
    TRIP_DAYS,
)
from moarcoal.storage import entry_checksum
from moarcoal.values.calculation import ValueSource
from moarcoal.values.model import ExposedValue, Period, ValueResult
from moarcoal.web.helpers import (
    global_year,
    module_state,
    user_of,
    values_of,
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


class CostLine(Enum):
    """Wie eine Zeile der Tabelle der Reisekosten in der Summe steht; der Wert ist die Klasse der
    Zeile in der Vorlage."""

    FIRST = "first"  # erster Posten
    ADDEND = "addend"  # weiterer Posten, mit „+“ davor
    TOTAL = "sum"  # die Summe


@dataclass(frozen=True)
class CostRow:
    """Eine Zeile der Tabelle der Reisekosten: Posten, Wert, bei 0 € die Begründung, Verweis."""

    label: str
    result: ValueResult
    line: CostLine
    reason: str = ""
    href: str = ""


def _decision(result: ValueResult) -> str:
    """Die Entscheidung im Rechenweg, die einen Betrag begründet (z. B. 0 € ohne Einzelposten)."""
    if not isinstance(result, ExposedValue) or result.items:
        return ""
    return " ".join(step.text for step in result.workings.steps if step.kind == "decision")


def _cost_rows(values: ValueSource, user: str, period: Period) -> list[CostRow]:
    """Reisekosten der Dienstreisen (Nr. 66 bis 69 der Anlage N) als Zeilen der kleinen Tabelle."""
    rows: list[CostRow] = []
    for label, key, line in (
        ("Fahrtkosten", TRAVEL_FARE, CostLine.FIRST),
        ("Übernachtungskosten", TRAVEL_LODGING, CostLine.ADDEND),
        ("Reisenebenkosten", TRAVEL_INCIDENTALS, CostLine.ADDEND),
        ("Summe der Reisekosten", TRAVEL_TOTAL, CostLine.TOTAL),
    ):
        result = values.get(key, user, period)
        href = f"#{TRIPS_ANCHOR}" if key == TRAVEL_FARE else ""
        rows.append(CostRow(label, result, line, _decision(result), href))
    return rows


def trips_context(
    request: Request,
    year: int,
    *,
    rows: list[TripRow] | None = None,
    error: str = "",
    problems: dict[int, str] | None = None,
    search: PlaceSearchView | None = None,
) -> dict[str, Any]:
    """Die Vorlagenwerte der Dienstreisen (`work/_trips.html`) eines Jahrs."""
    trips = trips_of(request, year)
    rate = KM_RATES.get(year)
    if rows is None:
        rows = [TripRow.from_trip(t, rate) for t in trips]
        rows.append(TripRow(places=place_prefill(trips)))
    period = Period.year(year)
    values = values_of(request)
    user = user_of(request)
    found = _statements(request, year, trips)
    return {
        "year": year,
        "rows": rows,
        "trip_anchor": trip_anchor,
        "error": error,
        "trip_count": len(trips),
        "total_km": sum(t.distance_km for t in trips),
        "rate": rate,
        "confirmation": confirmation_in(module_state(request, MODULE_KEY), year),
        "stand": trips_fingerprint(trips),
        "fare": values.get(TRAVEL_FARE, user, period),
        "trip_days": values.get(TRIP_DAYS, user, period),
        "costs": _cost_rows(values, user, period),
        "trips_anchor": TRIPS_ANCHOR,
        "statements": found,
        "to_take": sum(1 for s in found for t in s["trips"] if not t.taken),
        "germany": germany_map(),
        "map_places": sort_places(place_uses(trips), places_of(request), germany_map()),
        "search": search,
        "problems": problems or {},
        "min_date": f"{year}-01-01",
        "max_date": f"{year}-12-31",
    }
