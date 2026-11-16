"""Erste Tätigkeitsstätte und Arbeitsmittel: Nutzereingaben zur Anlage N, von Hand erfasst."""

import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.work.common import SCHEMA, TEXT_MAX, yearly_path
from moarcoal.storage import Entry, EntryKind, entry_kind

MAX_CENTS = 100_000_000
MAX_WORKDAYS = 250
DEFAULT_WORKDAYS = MAX_WORKDAYS - 30  # abzüglich 30 Urlaubstage
MAX_DISTANCE_KM = 1000
MAX_ABSENCE_DAYS = 366
DAYS_PER_WEEK = 7


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
    distance_km: int = Field(ge=0, le=MAX_DISTANCE_KM)
    description: str = Field(default="", max_length=TEXT_MAX)
    # Freiwillige Angaben zu Anlage N Nr. 28 und 31; fehlt eine, ist ihr Feld noch nicht
    # berechenbar.
    workdays_per_week: int | None = Field(default=None, ge=1, le=DAYS_PER_WEEK)
    absence_days: int | None = Field(default=None, ge=0, le=MAX_ABSENCE_DAYS)
    car_distance_km: int | None = Field(default=None, ge=0, le=MAX_DISTANCE_KM)

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


KINDS: tuple[EntryKind, ...] = (
    entry_kind(FirstWorkplace, SCHEMA, yearly_path),
    entry_kind(WorkEquipment, SCHEMA, yearly_path),
)
