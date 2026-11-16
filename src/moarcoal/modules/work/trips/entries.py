"""Dienstreisen und ihre Bestätigung als Einträge."""

import datetime
from collections.abc import Mapping

from pydantic import Field, model_validator

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.work.common import SCHEMA, TEXT_MAX, yearly_path
from moarcoal.storage import Entry, EntryAddress, EntryKind, entry_checksum, entry_kind
from moarcoal.values.findings import fingerprint

MAX_TRIP_KM = 100_000
MAX_PLACES = 20


class BusinessTrip(Entry):
    """Dienstreise im Steuerjahr, nur mit dem privaten Pkw: Orte in Reihenfolge, km der Reise.

    `end` leer heißt: eintägig (Ende = Start). Die Orte nennen den Rückweg ausdrücklich
    (A, B, A). Start und Ende liegen im Steuerjahr.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    start: datetime.date
    end: datetime.date | None = None
    places: tuple[str, ...] = Field(min_length=2, max_length=MAX_PLACES)
    distance_km: int = Field(gt=0, le=MAX_TRIP_KM)
    note: str = Field(default="", max_length=TEXT_MAX)

    @model_validator(mode="after")
    def _check_dates(self) -> "BusinessTrip":
        if self.end is not None and self.end < self.start:
            raise ValueError("Ende liegt vor dem Start")
        if any(day.year != self.year for day in (self.start, self.end or self.start)):
            raise ValueError("Start und Ende liegen nicht im Steuerjahr")
        if any(not place.strip() or len(place) > TEXT_MAX for place in self.places):
            raise ValueError("Ort leer oder zu lang")
        return self


def trips_fingerprint(trips: list[BusinessTrip]) -> str:
    """Stand der Dienstreisen eines Jahrs: ändert sich eine, ändert sich der Fingerabdruck."""
    return fingerprint(*sorted(entry_checksum(t) for t in trips))


class TripsConfirmation(Entry):
    """Bestätigung, dass die Dienstreisen eines Steuerjahrs vollständig sind (auch ohne Reisen).

    Sie gilt für genau den Stand, den `trips_fingerprint` nennt; jede Änderung an den Reisen
    hebt sie damit auf, ohne dass ein Schreibweg daran denken muss. Je Nutzer und Jahr höchstens
    eine.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    confirmed_on: datetime.date
    trips_fingerprint: str = Field(min_length=1)


def check_confirmation(
    entry: TripsConfirmation, entries: Mapping[EntryAddress, Entry]
) -> str | None:
    """Schreibweg: nur eine Bestätigung je Nutzer und Jahr, und nur für den Stand der Reisen."""
    mine = [
        e
        for e in entries.values()
        if isinstance(e, TripsConfirmation | BusinessTrip)
        and e.owner == entry.owner
        and e.year == entry.year
    ]
    if sum(isinstance(e, TripsConfirmation) for e in mine) > 1:
        return f"Für {entry.year} gibt es schon eine Bestätigung der Dienstreisen"
    trips = [e for e in mine if isinstance(e, BusinessTrip)]
    if entry.trips_fingerprint != trips_fingerprint(trips):
        return f"Die Dienstreisen {entry.year} haben sich inzwischen geändert"
    return None


KINDS: tuple[EntryKind, ...] = (
    entry_kind(BusinessTrip, SCHEMA, yearly_path),
    entry_kind(TripsConfirmation, SCHEMA, yearly_path, check=check_confirmation),
)
