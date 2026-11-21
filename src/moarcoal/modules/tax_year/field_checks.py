"""Die Gegenproben eines Felds der Anlage, wie seine Zeile sie zeigt.

Je Gegenseite (Übertragungsprotokoll, Schnappschuss der Abgabe, EStB) der Inhalt dort und ob er
zum Feld passt. Verglichen wird hier nicht: eine Abweichung ist ein Befund der jeweiligen
Gegenprobe (`protocol_check`, `snapshot_check`, `assessment_check`), die Zeile ordnet die Befunde
nur ihrem Feld zu. Ohne Befund passt ein berechnetes Feld, sobald die Gegenseite etwas zeigt.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from moarcoal.modules.tax_year.assessment_check import ASSESSMENT_DEVIATION
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.protocol_check import AMBIGUOUS, DEVIATION, MISSING
from moarcoal.modules.tax_year.snapshot_check import SNAPSHOT_DEVIATION
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import ValueKey, ValueRef

PROTOCOL = "Laut Protokoll"
SNAPSHOT = "Bei Abgabe"
ASSESSMENT = "Laut EStB"

_KINDS = {
    PROTOCOL: (DEVIATION, MISSING, AMBIGUOUS),
    SNAPSHOT: (SNAPSHOT_DEVIATION,),
    ASSESSMENT: (ASSESSMENT_DEVIATION,),
}


@dataclass(frozen=True)
class FieldCheck:
    """Eine Gegenprobe in der Zeile eines Felds: Gegenseite, ihr Inhalt, und entweder passt sie
    (`fits`), weicht ab (`deviation`: der Text des Befunds) oder bleibt ohne Urteil (beides leer,
    z. B. bei Feldern, die MoarCoal nicht berechnet)."""

    side: str
    shown: str
    fits: bool = False
    deviation: str = ""
    severity: Severity | None = None  # Schweregrad des Befunds bei einer Abweichung


def field_checks(
    field: FormField,
    *,
    transferred: Mapping[str, str] | None,
    frozen: Mapping[str, str] | None,
    printed: Mapping[ValueKey, Decimal],
    findings: Iterable[Finding],
) -> tuple[FieldCheck, ...]:
    """Die Gegenproben der Zeile von `field`; eine Gegenseite, die es im Jahr nicht gibt
    (`None` bzw. leer), entfällt, der Schnappschuss auch bei Feldern, die MoarCoal nicht
    berechnet."""
    mine = [f for f in findings if isinstance(f.target, ValueRef) and f.target.key == field.key]
    sides: list[tuple[str, str | None]] = []
    if transferred is not None:
        sides.append((PROTOCOL, transferred.get(field.elster_id or "")))
    if frozen is not None and field.computed:  # eingefroren werden nur berechnete Felder
        sides.append((SNAPSHOT, frozen.get(field.key)))
    if printed:
        sides.append((ASSESSMENT, field.show(printed[field.key]) if field.key in printed else None))
    checks: list[FieldCheck] = []
    for side, shown in sides:
        found = next((f for f in mine if f.kind in _KINDS[side]), None)
        if found is not None:
            checks.append(
                FieldCheck(side, shown or "–", deviation=found.message, severity=found.severity)
            )
        else:
            checks.append(FieldCheck(side, shown or "–", fits=field.computed and shown is not None))
    return tuple(checks)
