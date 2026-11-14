"""Daten des Moduls Arbeit: Angaben zur Anlage N, von Hand erfasst (Nutzereingaben)."""

import datetime
from collections.abc import Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from moarcoal.storage import Entry, EntryAddress, EntryKind, entry_checksum, entry_kind
from moarcoal.values.findings import fingerprint

SCHEMA = "work/1"
MIN_YEAR = 2000
MAX_YEAR = 2100
MAX_CENTS = 100_000_000
MAX_WAGE_CENTS = 100_000_000_000  # 1 Mrd. Euro
TEXT_MAX = 200
MAX_WORKDAYS = 250
DEFAULT_WORKDAYS = MAX_WORKDAYS - 30  # abzüglich 30 Urlaubstage
MAX_TRIP_KM = 100_000
MAX_PLACES = 20
MAX_ABSENCE_DAYS = 366


class UserInput(BaseModel):
    """Baustein Nutzereingabe: Betrag (ganze Cent, EUR), Datum und Beschreibung."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_cents: int = Field(gt=0, le=MAX_CENTS)
    date: datetime.date
    description: str = Field(min_length=1, max_length=TEXT_MAX)


class FirstWorkplace(Entry):
    """Erste Tätigkeitsstätte eines Steuerjahrs: Arbeitstage, einfache Entfernung in km und
    die Angaben zu Arbeitstagen je Woche, Urlaubs- und Krankheitstagen und Pkw-km.

    `workdays` sind die Tage, an denen der Nutzer die Tätigkeitsstätte aufgesucht hat (Anlage N
    „aufgesucht an Tagen“), nicht alle Arbeitstage des Jahrs (Homeoffice, Dienstreisen fehlen).
    Offen für die Ausarbeitung des Moduls Arbeit: Name, Formular und Abgrenzung danach richten.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    workdays: int = Field(ge=0, le=MAX_WORKDAYS)
    distance_km: int = Field(ge=0, le=1000)
    description: str = Field(default="", max_length=TEXT_MAX)
    # Freiwillige Angaben zu Anlage N Nr. 28 und 31; fehlt eine, ist ihr Feld noch nicht
    # berechenbar.
    workdays_per_week: int | None = Field(default=None, ge=1, le=7)
    absence_days: int | None = Field(default=None, ge=0, le=MAX_ABSENCE_DAYS)
    car_distance_km: int | None = Field(default=None, ge=0, le=1000)

    @field_validator("car_distance_km")
    @classmethod
    def _check_car_distance(cls, km: int | None, info: ValidationInfo) -> int | None:
        if km is not None and km > info.data.get("distance_km", km):
            raise ValueError("Mit dem Pkw gefahrene km liegen über der einfachen Entfernung")
        return km


class WorkEquipment(Entry):
    """Arbeitsmittel eines Steuerjahrs, ein Betrag je Eintrag."""

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    input: UserInput


class WageTaxCertificate(Entry):
    """Ergebnis des Einlesens einer Lohnsteuerbescheinigung (eDaten) zu genau einem Dokument.

    Beträge stehen in ganzen Cent, genau wie bescheinigt. `None` heißt: die Bescheinigung nennt die
    Angabe nicht (nie 0). `places` nennt je Angabe den vollen Feldnamen `data-name` als Fundstelle.
    `reader_version` nennt die Fassung der Einlese-Regel. Die Bescheinigung fällt mit dem Dokument
    weg; nach dem Löschen lässt sich die Datei erneut aufnehmen und wird neu eingelesen.
    """

    document: EntryAddress
    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    reader_version: int = Field(ge=1)
    tax_class: int | None = Field(default=None, ge=1, le=6)
    gross_wages_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    income_tax_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    soli_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    places: dict[str, str] = Field(default_factory=dict)


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


def yearly_path(
    entry: FirstWorkplace | WorkEquipment | WageTaxCertificate | BusinessTrip | TripsConfirmation,
) -> str:
    return f"users/{entry.owner}/work/{entry.year}.json"


KINDS: tuple[EntryKind, ...] = (
    entry_kind(FirstWorkplace, SCHEMA, yearly_path),
    entry_kind(WorkEquipment, SCHEMA, yearly_path),
    entry_kind(WageTaxCertificate, SCHEMA, yearly_path, falls_with="document"),
    entry_kind(BusinessTrip, SCHEMA, yearly_path),
    entry_kind(TripsConfirmation, SCHEMA, yearly_path, check=check_confirmation),
)
