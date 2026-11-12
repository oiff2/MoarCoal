"""Feld einer Anlage und seine Regeln: runden, anzeigen, Protokollfelder lesen, Abweichung nennen.

Die Werte der Felder sind gesetzlich gerundet, je nach Einheit und Richtung des Felds
(docs/recherche-runden-anlage-n.md). Welche Abweichung zugunsten des Steuerpflichtigen ist, leitet
das Feld aus derselben Angabe ab: bei Euro die Richtung, km zählen wie eine Ausgabe, Tage ohne.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from moarcoal.modules.tax_year.entries import ElsterId
from moarcoal.values.model import Amount, Unit, ValueKey, format_amount, parse_german_number


class Direction(StrEnum):
    """Richtung eines Euro-Felds: Einnahme oder Ausgabe; der Wert ist die Anzeige im Rechenweg."""

    INCOME = "Einnahme"
    EXPENSE = "Ausgabe"


class Rounding(StrEnum):
    """Wie der Wert eines Felds gerundet wird, bevor er einzutragen ist."""

    WHOLE_EUROS = "ganze Euro"  # zugunsten des Steuerpflichtigen, je nach Richtung
    EURO_CENTS = "Euro mit Cent"  # exakt
    WHOLE_KM = "volle km"  # abgerundet
    NONE = "ganzzahlig"  # Tage: schon ganzzahlig


@dataclass(frozen=True)
class AmbiguousLines:
    """Tage oder km stehen mehrfach im Protokoll; welche Zeile gilt, ist offen."""

    count: int


@dataclass(frozen=True)
class NotANumber:
    """Der Inhalt eines Protokollfelds ist keine Zahl."""

    content: str


@dataclass(frozen=True)
class FormField:
    """Ein Feld einer Anlage: Bezeichnung, E-Kennung (leer, solange unbekannt), Nr. im Vordruck.

    `key` ist der Schlüssel des Ausgewiesenen Werts, den das Steuerjahr dem Feld zuordnet.
    """

    key: ValueKey
    elster_id: ElsterId | None
    form_line: str
    label: str
    unit: Unit
    rounding: Rounding
    direction: Direction | None = None  # nur bei ganzen Euro

    def __post_init__(self) -> None:
        if (self.rounding is Rounding.WHOLE_EUROS) != (self.direction is not None):
            raise ValueError(f"{self.label}: Richtung gehört genau zu Feldern mit ganzen Euro")

    @property
    def whole_euros(self) -> bool:
        """Ob das Feld ganze Euro nimmt (angezeigt ohne Cent)."""
        return self.rounding is Rounding.WHOLE_EUROS

    @property
    def _whole_numbers(self) -> bool:
        """Ob das Feld nur ganze Zahlen nimmt (Nachkommastellen heißen: ungerundet)."""
        return self.rounding is not Rounding.EURO_CENTS

    @property
    def _more_is_favourable(self) -> bool | None:
        """Ob ein höherer Wert zugunsten des Steuerpflichtigen ist; bei Tagen keine Aussage."""
        if self.direction is Direction.INCOME:
            return False
        if self.direction is Direction.EXPENSE or self.unit is Unit.KM:
            return True
        return None

    def round(self, value: Decimal) -> tuple[Decimal, str | None]:
        """Der einzutragende Wert und der Grund der Rundung; passt der Wert schon, kein Grund."""
        match self.rounding:
            case Rounding.WHOLE_EUROS:
                income = self.direction is Direction.INCOME
                rounded = value.to_integral_value(ROUND_FLOOR if income else ROUND_CEILING)
                reason = f"{'abgerundet' if income else 'aufgerundet'}, {self.direction}"
            case Rounding.WHOLE_KM:
                rounded = value.to_integral_value(ROUND_FLOOR)
                reason = "auf volle km abgerundet"
            case _:
                return value, None
        return (value, None) if rounded == value else (rounded, reason)

    def show(self, value: Decimal) -> str:
        """Wert deutsch mit Einheit, ganze Euro ohne Cent: '87 €', '86,40 €', '12 km'."""
        return format_amount(Amount(value, self.unit), whole_euros=self.whole_euros)

    def read_protocol(self, contents: Sequence[str]) -> Decimal | AmbiguousLines | NotANumber:
        """Der übertragene Wert aus den Inhalten der Protokollfelder dieses Felds (mindestens
        einer): Euro-Zeilen werden summiert, Tage und km sind mehrfach mehrdeutig."""
        if self.unit is not Unit.EUR and len(contents) > 1:
            return AmbiguousLines(len(contents))
        total = Decimal(0)
        for content in contents:
            number = parse_german_number(content)
            if number is None:
                return NotANumber(content)
            total += number
        return total

    def explain_deviation(self, expected: Decimal, transferred: Decimal) -> str:
        """Text der Abweichung; liegt sie nur an der Rundung, mit Differenz und Richtung."""
        shown = self.show(expected)
        plain = f"Wert {shown}, Protokoll {self.show(transferred)}."
        if not self._whole_numbers:
            return plain
        if transferred != transferred.to_integral_value():
            return f"nicht gerundet: {self.show(transferred)} statt {shown}."
        difference = transferred - expected
        favourable = self._more_is_favourable
        if abs(difference) > 1 or favourable is None:
            return plain
        how = "aufgerundet" if difference > 0 else "abgerundet"
        side = "Gunsten" if (difference > 0) == favourable else "Ungunsten"
        return f"um {self.show(abs(difference))} {how}, zu deinen {side} (Wert {shown})."
