"""Was alle Teile von Arbeit teilen: Schema, Modulschlüssel, Textgrenze und der Speicherpfad."""

from typing import Protocol

SCHEMA = "work/1"
MODULE_KEY = "work"
TEXT_MAX = 200


class YearlyEntry(Protocol):
    @property
    def owner(self) -> str: ...

    @property
    def year(self) -> int: ...


def yearly_path(entry: YearlyEntry) -> str:
    return f"users/{entry.owner}/work/{entry.year}.json"


def work_url(year: int) -> str:
    """Die Seite Arbeit für ein Steuerjahr."""
    return f"/arbeit?jahr={year}"


TRIPS_ANCHOR = "dienstreisen"


def trips_url(year: int) -> str:
    """Die Tabelle der Dienstreisen auf der Seite Arbeit eines Steuerjahrs."""
    return f"{work_url(year)}#{TRIPS_ANCHOR}"


def trip_anchor(trip_id: str) -> str:
    """Anker der Zeile einer gespeicherten Dienstreise."""
    return f"reise-{trip_id}"


def trip_row_url(year: int, trip_id: str) -> str:
    """Die Zeile einer Dienstreise auf der Seite Arbeit ihres Steuerjahrs."""
    return f"{work_url(year)}#{trip_anchor(trip_id)}"


def trip_url(trip_id: str) -> str:
    """Die Adresse einer Dienstreise: leitet auf ihre Zeile (das Jahr kennt nur der Eintrag)."""
    return f"/arbeit/dienstreisen/reise/{trip_id}"
