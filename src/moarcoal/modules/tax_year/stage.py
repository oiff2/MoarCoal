"""Die Stufe einer Zeile der Anlage und die Stufe darüber: reine Regeln für Statusstreifen und Baum.

Eine Zeile der Feldtabelle hat eine Stufe (`Stage`) mit den Gründen dafür (`Grading`). Dieselbe
Funktion, `grade_row`, liefert sie dem Statusstreifen der Anlage-Seite und, über `combine`
zusammengefasst, den Punkten im Baum der Übersicht (Seite, Anlage); es gibt die Regeln nur hier
(Prinzipien 4 und 7). Die Regeln sind bewusst vorläufig (Ticket #248):

- rot (`ERROR`): ein Befund oder eine abweichende Gegenprobe mit Schweregrad Fehler.
- gelb (`OPEN`): alles andere, was einen Eintrag hat oder offen ist: Hinweis, Warnung, ein
  erwarteter Beleg, ein nicht belegter Betrag, eine Angabe ohne passende Gegenprobe, ein Wert,
  der noch nicht berechenbar ist.
- grün (`GOOD`): ein belegter Betrag oder eine passende Gegenprobe, nichts offen.
- kein Punkt (`NONE`): nichts davon.

Rot geht vor gelb, gelb vor grün; ein Stufe darüber trägt den schlechtesten seiner Teile.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum, auto

from moarcoal.modules.tax_year.field_checks import FieldCheck
from moarcoal.values.findings import Severity
from moarcoal.values.model import Backing, ExposedValue, NotYetComputable, ValueResult


class Stage(IntEnum):
    """Stufe einer Zeile; die Ordnung ist der Vorrang: der größere Wert zählt für den Stand
    darüber."""

    NONE = 0
    GOOD = 1
    OPEN = 2
    ERROR = 3


class Reason(Enum):
    """Warum etwas offen oder ein Fehler ist; die Reihenfolge ist die der Anzeige im Tooltip."""

    ERROR = auto()
    WARNING = auto()
    NOTE = auto()
    EXPECTED = auto()
    UNPROVEN = auto()
    ENTERED = auto()
    NOT_YET = auto()


_WORDS = {
    Reason.ERROR: ("Fehler", "Fehler"),
    Reason.WARNING: ("Warnung", "Warnungen"),
    Reason.NOTE: ("Hinweis", "Hinweise"),
    Reason.EXPECTED: ("Beleg erwartet", "Belege erwartet"),
    Reason.UNPROVEN: ("Betrag nicht belegt", "Beträge nicht belegt"),
    Reason.ENTERED: ("Angabe nicht belegt", "Angaben nicht belegt"),
    Reason.NOT_YET: ("Feld noch nicht berechenbar", "Felder noch nicht berechenbar"),
}
_SEVERITY_REASON = {
    Severity.ERROR: Reason.ERROR,
    Severity.WARNING: Reason.WARNING,
    Severity.NOTE: Reason.NOTE,
}


@dataclass(frozen=True)
class Grading:
    """Die Stufe mit den Gründen dahinter, gezählt je Grund."""

    stage: Stage = Stage.NONE
    reasons: tuple[tuple[Reason, int], ...] = ()

    @property
    def title(self) -> str:
        """Der Grund in Worten für den Tooltip, z. B. „1 Hinweis, 2 Belege erwartet“."""
        if self.reasons:
            return ", ".join(f"{n} {_WORDS[r][0 if n == 1 else 1]}" for r, n in self.reasons)
        return "belegt oder passt, nichts offen" if self.stage is Stage.GOOD else ""


def _status(stage: Stage, reasons: Iterable[Reason]) -> Grading:
    counted = Counter(reasons)
    return Grading(stage, tuple((r, counted[r]) for r in Reason if counted[r]))


def grade_row(result: ValueResult | None, checks: Sequence[FieldCheck], *, filled: bool) -> Grading:
    """Die Stufe der Zeile eines Felds aus dem Ergebnis des Werts (`None`: das Feld hat keins) und
    seinen Gegenproben. `filled`: das Eintipp- oder Textfeld hat einen Inhalt; ohne passende
    Gegenprobe ist er nicht belegt (gelb)."""
    stage = Stage.NONE
    reasons: list[Reason] = []
    if isinstance(result, NotYetComputable):
        stage = Stage.OPEN
        reasons.append(Reason.NOT_YET)
    elif isinstance(result, ExposedValue):
        match result.backing:
            case Backing.PROVEN:
                stage = Stage.GOOD
            case Backing.PENDING:
                stage = Stage.OPEN
                reasons.append(Reason.EXPECTED)
            case Backing.ASSUMED:
                stage = Stage.OPEN
                reasons.append(Reason.UNPROVEN)
    for check in checks:
        if check.hidden:
            continue  # ausgeblendet: weder gelb noch rot, aber auch kein „passt“
        if check.deviation:
            reason = _SEVERITY_REASON.get(check.severity or Severity.NOTE, Reason.NOTE)
            stage = max(stage, Stage.ERROR if reason is Reason.ERROR else Stage.OPEN)
            reasons.append(reason)
        elif check.fits:
            stage = max(stage, Stage.GOOD)
    if filled and not any(c.fits for c in checks):
        stage = max(stage, Stage.OPEN)
        reasons.append(Reason.ENTERED)
    return _status(stage, reasons)


def combine(parts: Iterable[Grading]) -> Grading:
    """Die Stufe über mehreren Teilen: die schlechteste Stufe, die Gründe summiert."""
    stage = Stage.NONE
    reasons: list[Reason] = []
    for part in parts:
        stage = max(stage, part.stage)
        for reason, n in part.reasons:
            reasons.extend([reason] * n)
    return _status(stage, reasons)
