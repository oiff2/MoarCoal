"""Befunde, die die Datenebene beim Rechnen erzeugt (im Durchstich: Zyklus)."""

from dataclasses import dataclass
from enum import StrEnum

from moarcoal.values.model import ValueRef


class Severity(StrEnum):
    """Schweregrad eines Befunds; der Wert ist die Anzeige."""

    NOTE = "Hinweis"
    WARNING = "Warnung"
    ERROR = "Fehler"


@dataclass(frozen=True)
class Finding:
    """Ein Befund: Befundart (`kind`), Schweregrad, betroffener Wert, Text und ggf. Kette."""

    kind: str
    severity: Severity
    target: ValueRef
    message: str
    chain: tuple[ValueRef, ...] = ()


CYCLE = "cycle"
