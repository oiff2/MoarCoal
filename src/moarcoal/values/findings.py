"""Befunde und Befundarten; die Datenebene erzeugt beim Rechnen den Zyklus, Module den Rest."""

from dataclasses import dataclass
from enum import StrEnum

from moarcoal.values.model import ValueRef


class Severity(StrEnum):
    """Schweregrad eines Befunds; der Wert ist die Anzeige."""

    NOTE = "Hinweis"
    WARNING = "Warnung"
    ERROR = "Fehler"


@dataclass(frozen=True)
class FindingKind:
    """Eine Befundart, die ein Modul anmeldet: Schlüssel (`<modul>.<name>`) und Titel."""

    key: str
    title: str


@dataclass(frozen=True)
class Finding:
    """Ein Befund: Befundart (`kind`), Schweregrad, betroffener Wert, Text und ggf. Kette.

    `href` führt zur Stelle, an der man den Befund prüft (leer: kein Link).
    """

    kind: str
    severity: Severity
    target: ValueRef
    message: str
    chain: tuple[ValueRef, ...] = ()
    href: str = ""


CYCLE = "cycle"
