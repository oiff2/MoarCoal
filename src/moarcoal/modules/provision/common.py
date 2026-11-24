"""Was alle Teile von Vorsorge teilen: Schema, Modulschlüssel und der Speicherpfad."""

from collections.abc import Sequence
from typing import Protocol

from moarcoal.values.calculation import Calculation

SCHEMA = "provision/1"
MODULE_KEY = "provision"


class YearlyEntry(Protocol):
    @property
    def owner(self) -> str: ...

    @property
    def year(self) -> int: ...


def yearly_path(entry: YearlyEntry) -> str:
    return f"users/{entry.owner}/provision/{entry.year}.json"


def require_current_reading(
    calculation: Calculation,
    label: str,
    year: int,
    *,
    reader_version: int,
    current_version: int,
    unrecognized: Sequence[str],
) -> None:
    """Der Wert ist noch nicht berechenbar, wenn die Bescheinigung (`label`, z. B. „Eine
    Anbieterbescheinigung Basisrente“) mit einer älteren Einlese-Regel eingelesen ist oder Pfade
    enthält, die die Regel nicht kennt (die Meldung nennt sie): ob ein Betrag darunter ist, ist
    offen."""
    if reader_version < current_version:
        calculation.not_yet(
            f"{label} {year} ist mit einer älteren Einlese-Regel eingelesen; "
            "sie wird beim nächsten Start neu eingelesen"
        )
    if unrecognized:
        calculation.not_yet(
            f"{label} {year} enthält Angaben, die MoarCoal nicht kennt "
            f"({', '.join(unrecognized)}); ob ein Betrag darunter ist, ist offen"
        )
