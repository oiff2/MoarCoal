"""Gegenproben in der Zeile eines Felds: passt, weicht ab oder ohne Urteil."""

from decimal import Decimal

from moarcoal.modules.tax_year.anlage_n import ANLAGE_N
from moarcoal.modules.tax_year.field_checks import FieldCheck, field_checks
from moarcoal.modules.tax_year.fields import FieldMeaning, FormField, NotComputed
from moarcoal.modules.tax_year.protocol_check import DEVIATION
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import Period, ValueRef

COMPUTED = next(f for f in ANLAGE_N.fields[2025] if f.computed)
# Anlage N 2025 berechnet jedes Feld mit Betrag (#165); ein nicht berechnetes Feld wie in den
# übrigen Anlagen, aus einem berechneten abgeleitet
NOT_COMPUTED = FormField(
    FieldMeaning(COMPUTED.elster_id, NotComputed()), COMPUTED.form_line, COMPUTED.label, form="N"
)


def deviation(message: str) -> Finding:
    ref = ValueRef(COMPUTED.key, "anna", Period.year(2025), None)
    return Finding(DEVIATION, Severity.WARNING, ref, message)


def test_a_computed_field_fits_when_the_other_side_shows_something_and_no_finding_says_else():
    checks = field_checks(
        COMPUTED,
        transferred={COMPUTED.elster_id: "12"},
        frozen=None,
        printed={},
        findings=[],
    )

    assert checks == (FieldCheck("Laut Protokoll", "12", fits=True),)


def test_the_finding_of_the_field_makes_the_check_deviate():
    checks = field_checks(
        COMPUTED,
        transferred={},
        frozen={COMPUTED.key: "5 €"},
        printed={COMPUTED.key: Decimal(5)},
        findings=[deviation("Das Feld fehlt im Übertragungsprotokoll.")],
    )

    protocol, frozen, assessment = checks
    assert protocol.shown == "–" and protocol.severity is Severity.WARNING
    assert protocol.deviation == "Das Feld fehlt im Übertragungsprotokoll."
    assert frozen.fits and assessment.fits


def test_a_field_moarcoal_does_not_compute_shows_the_other_side_without_judgment():
    (check,) = field_checks(
        NOT_COMPUTED,
        transferred={NOT_COMPUTED.elster_id: "Ja"},
        frozen={},  # nicht berechnet: nie eingefroren, die Gegenprobe entfällt
        printed={},
        findings=[],
    )

    assert check == FieldCheck("Laut Protokoll", "Ja")
