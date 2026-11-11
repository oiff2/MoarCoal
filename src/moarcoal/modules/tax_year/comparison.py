"""Abgleich der Felder der Anlage N mit dem Übertragungsprotokoll (Befunde des Steuerjahrs).

Verglichen wird exakt und ohne Toleranz gegen den gerundeten Wert des Felds (das Steuerjahr rundet
nach Einheit und Richtung, siehe `anlage_n`). Weicht das Protokoll nur durch Rundung ab, nennt der
Text Differenz und Richtung. Mehrere Zeilen derselben E-Kennung werden bei EUR-Feldern summiert;
bei Tagen und km sind sie mehrdeutig.
"""

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation

from moarcoal.modules.tax_year.anlage_n import FORMS, Direction, FormField, show
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolLine, ProtocolReading
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding, FindingKind, Severity
from moarcoal.values.model import ExposedValue, Period, Unit, ValueRef

DEVIATION = "tax_year.protocol_deviation"
MISSING = "tax_year.protocol_missing"
AMBIGUOUS = "tax_year.protocol_ambiguous"
UNKNOWN_ELSTER_ID = "tax_year.protocol_unknown_elster_id"

FINDING_KINDS = (
    FindingKind(DEVIATION, "Übertragungsprotokoll weicht vom Wert ab"),
    FindingKind(MISSING, "Feld fehlt im Übertragungsprotokoll"),
    FindingKind(AMBIGUOUS, "Feld kommt im Übertragungsprotokoll mehrfach vor"),
    FindingKind(UNKNOWN_ELSTER_ID, "E-Kennung unbekannt, nicht abgleichbar"),
)

GERMAN_NUMBER = re.compile(r"-?\d{1,3}(\.\d{3})*(,\d+)?|-?\d+(,\d+)?")


def parse_german_number(text: str) -> Decimal | None:
    """'1.234,56' -> 1234.56; ein angehängtes € oder EUR ist erlaubt; sonst `None`."""
    cleaned = text.strip().removesuffix("€").removesuffix("EUR").strip()
    if not GERMAN_NUMBER.fullmatch(cleaned):
        return None
    try:
        return Decimal(cleaned.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def latest_reading(state: ModuleState, year: int) -> ProtocolReading | None:
    """Das zuletzt aufgenommene Protokoll des Jahrs.

    Maßgeblich ist `taken_in_at` seines Dokuments, bei Gleichstand die `id` des Protokolls.
    """
    taken = {d.address: d.taken_in_at for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [r for r in state.all(ProtocolReading) if r.year == year and r.document in taken]
    if not readings:
        return None

    def order(reading: ProtocolReading) -> tuple[bool, str, str]:
        moment = taken[reading.document]
        return (moment is not None, moment.isoformat() if moment else "", reading.id)

    return max(readings, key=order)


def protocol_url(reading: ProtocolReading, data_name: str = "") -> str:
    """Seite des Protokolls, auf Wunsch mit Sprung zur Zeile."""
    base = f"/steuerjahr/uebertragungsprotokolle/{reading.id}"
    return f"{base}#{data_name}" if data_name else base


def _sum(lines: list[ProtocolLine]) -> Decimal | None:
    numbers = [parse_german_number(line.content) for line in lines]
    if any(n is None for n in numbers):
        return None
    return sum((n for n in numbers if n is not None), Decimal(0))


def _deviation_text(field: FormField, expected: Decimal, transferred: Decimal) -> str:
    """Text der Abweichung; liegt sie nur an der Rundung, mit Differenz und Richtung."""
    shown = show(expected, field.unit)
    plain = f"Wert {shown}, Protokoll {show(transferred, field.unit)}."
    if not field.whole_numbers:
        return plain
    if transferred != transferred.to_integral_value():
        return f"nicht gerundet: {show(transferred, field.unit)} statt {shown}."
    difference = transferred - expected
    if abs(difference) > 1 or field.direction is None and field.unit is not Unit.KM:
        return plain
    # Zu Ungunsten: weniger Ausgabe bzw. Entfernung, mehr Einnahme.
    unfavorable = (difference > 0) == (field.direction is Direction.INCOME)
    how = "aufgerundet" if difference > 0 else "abgerundet"
    side = "Ungunsten" if unfavorable else "Gunsten"
    return f"um {show(abs(difference), field.unit)} {how}, zu deinen {side} (Wert {shown})."


def _field_findings(
    field: FormField, ref: ValueRef, value: ExposedValue, reading: ProtocolReading
) -> Iterator[Finding]:
    name = f"Anlage N Nr. {field.form_line}, {field.label} ({field.elster_id})"
    lines = [line for line in reading.lines if line.elster_id == field.elster_id]
    if not lines:
        if value.amount.value == 0:
            return  # ELSTER überträgt leere Felder nicht; 0 und fehlendes Feld stimmen überein
        yield Finding(
            MISSING,
            Severity.WARNING,
            ref,
            f"{name}: Das Feld fehlt im Übertragungsprotokoll.",
            href=protocol_url(reading),
        )
        return
    first = protocol_url(reading, lines[0].data_name)
    if field.unit is not Unit.EUR and len(lines) > 1:
        yield Finding(
            AMBIGUOUS,
            Severity.WARNING,
            ref,
            f"{name}: Das Feld kommt {len(lines)}-mal im Protokoll vor; "
            "ein Vergleich ist nicht möglich.",
            href=first,
        )
        return
    transferred = _sum(lines)
    shown = show(value.amount.value, value.amount.unit)
    if transferred is None:
        text = f"Wert {shown}, Protokoll „{lines[0].content}“ ist keine Zahl."
    elif transferred != value.amount.value:
        text = _deviation_text(field, value.amount.value, transferred)
    else:
        return
    yield Finding(DEVIATION, Severity.WARNING, ref, f"{name}: {text}", href=first)


def protocol_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Befunde des Abgleichs für das Jahr; ohne aufgenommenes Protokoll gibt es keinen Abgleich."""
    fields = FORMS.get(year)
    reading = latest_reading(state, year)
    if fields is None or reading is None:
        return []
    found: list[Finding] = []
    for field in fields:
        period = Period.year(year)
        result = values.get(field.key, state.user, period)
        ref = ValueRef(field.key, state.user, period, None)
        if field.elster_id is None:
            found.append(
                Finding(
                    UNKNOWN_ELSTER_ID,
                    Severity.NOTE,
                    ref,
                    f"Anlage N, {field.label}: E-Kennung unbekannt, nicht abgleichbar.",
                    href=protocol_url(reading),
                )
            )
        elif isinstance(result, ExposedValue):  # sonst gibt es nichts zu vergleichen
            found.extend(_field_findings(field, ref, result, reading))
    return found
