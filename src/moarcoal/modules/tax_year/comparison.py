"""Sammelstelle der Befunde des Steuerjahrs: Gegenprobe mit dem Übertragungsprotokoll
(`protocol_check`), Abweichung zum Schnappschuss der Abgabe (`snapshot_check`) und Abgleich des
EStB mit dem Schnappschuss (`assessment_check`)."""

from collections.abc import Sequence

from moarcoal.modules.tax_year import assessment_check, protocol_check, snapshot_check
from moarcoal.modules.tax_year.anlage_n import ANLAGEN
from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.assessment_check import assessment_findings
from moarcoal.modules.tax_year.protocol_check import protocol_findings
from moarcoal.modules.tax_year.snapshot_check import snapshot_findings
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding

FINDING_KINDS = (
    *protocol_check.FINDING_KINDS,
    *snapshot_check.FINDING_KINDS,
    *assessment_check.FINDING_KINDS,
)


def module_findings(
    state: ModuleState,
    values: ValueSource,
    year: int,
    anlagen: Sequence[Anlage] = ANLAGEN,
) -> list[Finding]:
    """Alle Befunde des Steuerjahrs: Abgleich mit dem Protokoll, Abweichung zum Schnappschuss und
    Abgleich des EStB mit dem Schnappschuss."""
    return [
        *protocol_findings(state, values, year, anlagen),
        *snapshot_findings(state, values, year, anlagen),
        *assessment_findings(state, year, anlagen),
    ]
