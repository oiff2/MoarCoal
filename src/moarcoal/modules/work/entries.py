"""Daten des Moduls Arbeit: Angaben zur Anlage N, von Hand erfasst (Nutzereingaben)."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage import Entry, EntryKind, entry_kind

SCHEMA = "work/1"
MIN_YEAR = 2000
MAX_YEAR = 2100
MAX_CENTS = 100_000_000
TEXT_MAX = 200
MAX_WORKDAYS = 250
DEFAULT_WORKDAYS = MAX_WORKDAYS - 30  # abzüglich 30 Urlaubstage


class UserInput(BaseModel):
    """Baustein Nutzereingabe: Betrag (ganze Cent, EUR), Datum und Beschreibung."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_cents: int = Field(gt=0, le=MAX_CENTS)
    date: datetime.date
    description: str = Field(min_length=1, max_length=TEXT_MAX)


class FirstWorkplace(Entry):
    """Erste Tätigkeitsstätte eines Steuerjahrs: Arbeitstage und einfache Entfernung in km.

    `workdays` sind die Tage, an denen der Nutzer die Tätigkeitsstätte aufgesucht hat (Anlage N
    „aufgesucht an Tagen“), nicht alle Arbeitstage des Jahrs (Homeoffice, Dienstreisen fehlen).
    Offen für die Ausarbeitung des Moduls Arbeit: Name, Formular und Abgrenzung danach richten.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    workdays: int = Field(ge=0, le=MAX_WORKDAYS)
    distance_km: int = Field(ge=0, le=1000)
    description: str = Field(default="", max_length=TEXT_MAX)


class WorkEquipment(Entry):
    """Arbeitsmittel eines Steuerjahrs, ein Betrag je Eintrag."""

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    input: UserInput


def yearly_path(entry: FirstWorkplace | WorkEquipment) -> str:
    return f"users/{entry.owner}/work/{entry.year}.json"


KINDS: tuple[EntryKind, ...] = (
    entry_kind(FirstWorkplace, SCHEMA, yearly_path),
    entry_kind(WorkEquipment, SCHEMA, yearly_path),
)
