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
