"""Abgleich der Felder der Anlage N mit dem Übertragungsprotokoll (Befunde des Steuerjahrs).

Verglichen wird exakt und ohne Toleranz: Der Wert wird nicht gerundet, auch wenn früher gerundete
Beträge eingereicht wurden. Gesetzliches Runden kommt später. Mehrere Zeilen derselben E-Kennung
werden bei EUR-Feldern summiert; bei Tagen und km sind sie mehrdeutig.
"""

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation

from moarcoal.modules.tax_year.anlage_n import FORMS, FormField
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolLine, ProtocolReading
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding, FindingKind, Severity
from moarcoal.values.model import ExposedValue, Period, Unit, ValueRef

DEVIATION = "tax_year.protocol_deviation"
MISSING = "tax_year.protocol_missing"
AMBIGUOUS = "tax_year.protocol_ambiguous"
UNKNOWN_EKZ = "tax_year.protocol_unknown_ekz"

FINDING_KINDS = (
    FindingKind(DEVIATION, "Übertragungsprotokoll weicht vom Wert ab"),
    FindingKind(MISSING, "Feld fehlt im Übertragungsprotokoll"),
    FindingKind(AMBIGUOUS, "Feld kommt im Übertragungsprotokoll mehrfach vor"),
    FindingKind(UNKNOWN_EKZ, "E-Kennung unbekannt, nicht abgleichbar"),
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
    """Das zuletzt aufgenommene Protokoll des Jahrs (nach `taken_in_at` seines Dokuments)."""
    taken = {d.address: d.taken_in_at for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [r for r in state.all(ProtocolReading) if r.year == year and r.document in taken]
    if not readings:
        return None

    def order(reading: ProtocolReading) -> tuple[bool, str]:
        moment = taken[reading.document]
        return (moment is not None, moment.isoformat() if moment else "")

    return max(readings, key=order)


def protocol_url(reading: ProtocolReading, data_name: str = "") -> str:
    """Seite des Protokolls, auf Wunsch mit Sprung zur Zeile."""
    base = f"/steuerjahr/uebertragungsprotokolle/{reading.id}"
    return f"{base}#{data_name}" if data_name else base


def _shown(value: Decimal, unit: Unit) -> str:
    text = f"{value:.2f}" if unit is Unit.EUR else f"{value.normalize():f}"
    text = text.replace(".", ",")
    return f"{text} €" if unit is Unit.EUR else f"{text} {unit.value}"


def _sum(lines: list[ProtocolLine]) -> Decimal | None:
    numbers = [parse_german_number(line.content) for line in lines]
    if any(n is None for n in numbers):
        return None
    return sum((n for n in numbers if n is not None), Decimal(0))


def _field_findings(
    field: FormField, ref: ValueRef, value: ExposedValue, reading: ProtocolReading
) -> Iterator[Finding]:
    name = f"Anlage N Nr. {field.form_line}, {field.label} ({field.ekz})"
    lines = [line for line in reading.lines if line.ekz == field.ekz]
    if not lines:
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
    shown = _shown(value.amount.value, value.amount.unit)
    if transferred is None:
        text = f"Wert {shown}, Protokoll „{lines[0].content}“ ist keine Zahl."
    elif transferred != value.amount.value:
        text = f"Wert {shown}, Protokoll {_shown(transferred, field.unit)}."
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
        if field.ekz is None:
            found.append(
                Finding(
                    UNKNOWN_EKZ,
                    Severity.NOTE,
                    ref,
                    f"Anlage N, {field.label}: E-Kennung unbekannt, nicht abgleichbar.",
                    href=protocol_url(reading),
                )
            )
        elif isinstance(result, ExposedValue):  # sonst gibt es nichts zu vergleichen
            found.extend(_field_findings(field, ref, result, reading))
    return found
