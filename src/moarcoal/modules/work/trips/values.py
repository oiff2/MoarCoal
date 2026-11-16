"""Ausgewiesene Werte der Dienstreisen: Tage, Fahrtkosten, Summe der Reisekosten.

Die Fahrtkosten sind die km des Jahrs mal dem km-Satz des Jahrs. Ohne Reisen gilt nur die
Bestätigung als vollständig (dann 0); sonst sind die Werte noch nicht berechenbar.
"""

from collections.abc import Callable

from moarcoal.modules.work.trips.entries import BusinessTrip
from moarcoal.modules.work.trips.table import (
    KM_RATES,
    confirmation_in,
    format_places,
    km_amount,
    trips_in,
)
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import Calculation, ValueSource
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.findings import Finding, FindingKind, Severity
from moarcoal.values.model import Amount, Period, Unit, UserInputLocator, ValueKey, ValueRef

TRIP_DAYS = ValueKey("work.trip_days")
TRAVEL_FARE = ValueKey("work.travel_fare")
TRAVEL_TOTAL = ValueKey("work.travel_total")


def _trips_with_items(
    calculation: Calculation, item_amount: Callable[[BusinessTrip], Amount]
) -> list[BusinessTrip]:
    """Die Reisen des Jahrs, je Reise ein Posten mit `item_amount`.

    Ohne Reisen gilt nur die Bestätigung als vollständig (dann ausdrücklich keine); sonst ist der
    Wert noch nicht berechenbar."""
    year = calculation.year
    trips = trips_in(calculation.own, year)
    if not trips and confirmation_in(calculation.own, year) is None:
        calculation.not_yet(
            f"Für {year} sind keine Dienstreisen erfasst und nicht als vollständig bestätigt"
        )
    for trip in trips:
        label = f"Dienstreise {trip.start:%d.%m.%Y}, {format_places(trip.places)}"
        calculation.item(label, item_amount(trip), UserInputLocator(trip.address))
    if not trips:
        calculation.decide(f"Dienstreisen {year} sind als vollständig bestätigt, es gab keine")
    return trips


def _days(trip: BusinessTrip) -> int:
    return ((trip.end or trip.start) - trip.start).days + 1


def compute_trip_days(calculation: Calculation) -> Amount:
    """Dienstreisetage des Jahrs: je Reise Ende minus Start plus 1, ohne Ende ein Tag."""
    trips = _trips_with_items(calculation, lambda trip: Amount.of(_days(trip), Unit.DAYS))
    return calculation.step(
        "Summe der Dienstreisetage", Amount.of(sum(_days(t) for t in trips), Unit.DAYS)
    )


def compute_travel_fare(calculation: Calculation) -> Amount:
    """Fahrtkosten mit dem privaten Pkw: erst alle km des Jahrs summieren, dann mal km-Satz."""
    year = calculation.year
    rate = KM_RATES.get(year)
    if rate is None:
        calculation.not_yet(f"Für {year} ist der km-Satz noch nicht hinterlegt")
    trips = _trips_with_items(calculation, lambda trip: Amount.of(trip.distance_km, Unit.KM))
    total_km = sum(t.distance_km for t in trips)
    calculation.step("Summe der km", Amount.of(total_km, Unit.KM))
    rate_text = f"{rate:.2f}".replace(".", ",")
    return calculation.step(
        f"{total_km} km × {rate_text} €/km", Amount(km_amount(total_km, rate), Unit.EUR)
    )


def compute_travel_total(calculation: Calculation) -> Amount:
    """Summe der Reisekosten: erfasst sind nur Fahrtkosten, Verpflegung, Übernachtung und
    Nebenkosten rechnet der Arbeitgeber ab."""
    item = calculation.use(TRAVEL_FARE, label="Fahrtkosten")
    if item is None:
        calculation.not_applicable("Fahrtkosten entfallen")
    return calculation.step("Summe der Reisekosten (nur Fahrtkosten erfasst)", item.amount)


TRIPS_TO_FILL = "work.trips_to_fill"

FINDING_KINDS = (FindingKind(TRIPS_TO_FILL, "Dienstreisen noch auszufüllen"),)


def trip_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Hinweis: Dienstreisen noch auszufüllen und zu bestätigen."""
    if confirmation_in(state, year) is not None:
        return []
    text = (
        f"Dienstreisen {year} noch auszufüllen: erfassen und als vollständig bestätigen "
        "(auch wenn es keine gab)."
    )
    ref = ValueRef(TRAVEL_FARE, state.user, Period.year(year), None)
    return [Finding(TRIPS_TO_FILL, Severity.NOTE, ref, text, href=f"/arbeit/dienstreisen/{year}")]


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            TRIP_DAYS,
            "Tage der Dienstreisen im Steuerjahr",
            Unit.DAYS,
            TimeKind.PERIOD,
        ),
        compute_trip_days,
    ),
    ValueDefinition(
        CatalogEntry(
            TRAVEL_FARE,
            "Fahrtkosten der Dienstreisen mit dem privaten Pkw im Steuerjahr",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_travel_fare,
    ),
    ValueDefinition(
        CatalogEntry(
            TRAVEL_TOTAL,
            "Summe der Reisekosten der Dienstreisen im Steuerjahr",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_travel_total,
    ),
)
