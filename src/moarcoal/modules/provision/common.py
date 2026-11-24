"""Was alle Teile von Vorsorge teilen: Schema, Modulschlüssel und der Speicherpfad."""

from typing import Protocol

SCHEMA = "provision/1"
MODULE_KEY = "provision"


class YearlyEntry(Protocol):
    @property
    def owner(self) -> str: ...

    @property
    def year(self) -> int: ...


def yearly_path(entry: YearlyEntry) -> str:
    return f"users/{entry.owner}/provision/{entry.year}.json"
