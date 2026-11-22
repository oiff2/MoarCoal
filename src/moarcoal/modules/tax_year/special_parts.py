"""Sonderteile einer Anlage: was eine Seite der Anlage zeigt, das kein Feld ist.

Ein Sonderteil ist eine reine Funktion (Stand, Jahr, Anfrageparameter → Daten), die Vorlage, die
sie einbindet, und die Stelle auf der Seite. Die Anlage meldet ihre Sonderteile an
(`Anlage.parts`); die Anlage-Ansicht ruft die Funktionen auf, die Vorlage der Seite bindet die
Teile ein. Route und Vorlage fragen nie nach der Anlage selbst.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from moarcoal.modules.tax_year.church_tax_view import PaymentForm
from moarcoal.registration import ModuleState


class Place(StrEnum):
    """Wo ein Sonderteil auf der Seite steht."""

    TOP = "top"  # oben, nur auf der ersten Seite der Anlage
    BOTTOM = "bottom"  # unten, auf jeder Seite der Anlage


@dataclass(frozen=True)
class PageParams:
    """Die Anfrageparameter der Seite, soweit Sonderteile sie brauchen: das aufgeklappte
    Formular (`entry`, Adresse im Aufruf) und das abgeschickte, abgewiesene Formular der
    Kirchensteuerzahlungen (`sent`)."""

    entry: str = ""
    sent: PaymentForm | None = None


type PartData = Callable[[ModuleState, int, PageParams], object]
"""Die Daten eines Sonderteils aus dem Stand des Moduls, dem Jahr und den Anfrageparametern."""


@dataclass(frozen=True)
class SpecialPart:
    """Ein Sonderteil einer Anlage: `data` liefert, was die Vorlage `template` zeigt, `place` sagt
    wo. Die Vorlage bekommt die Daten als `data`."""

    template: str
    place: Place
    data: PartData
