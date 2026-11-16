"""Gegenprobe mit dem Übertragungsprotokoll: Felder der Anlage N und Struktur des Jahres (Befunde).

Verglichen wird exakt und ohne Toleranz gegen den gerundeten Wert des Felds (das Steuerjahr rundet
nach Einheit und Richtung, siehe `fields`). Weicht das Protokoll nur durch Rundung ab, nennt der
Text Differenz und Richtung. Mehrere Zeilen derselben E-Kennung werden bei EUR-Feldern summiert;
bei Tagen und km sind sie mehrdeutig.
"""

from collections.abc import Iterator, Mapping

from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading, taken_order
from moarcoal.modules.tax_year.fields import AmbiguousLines, FormField, Forms, NotANumber
from moarcoal.modules.tax_year.links import protocol_url
from moarcoal.modules.tax_year.structure import FormStructure
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding, FindingKind, Severity, fingerprint
from moarcoal.values.model import ExposedValue, Period, ValueRef

DEVIATION = "tax_year.protocol_deviation"
MISSING = "tax_year.protocol_missing"
AMBIGUOUS = "tax_year.protocol_ambiguous"
UNKNOWN_ELSTER_ID = "tax_year.protocol_unknown_elster_id"
LINE_MISMATCH = "tax_year.protocol_line_mismatch"

FINDING_KINDS = (
    FindingKind(DEVIATION, "Übertragungsprotokoll weicht vom Wert ab"),
    FindingKind(MISSING, "Feld fehlt im Übertragungsprotokoll"),
    FindingKind(AMBIGUOUS, "Feld kommt im Übertragungsprotokoll mehrfach vor"),
    FindingKind(UNKNOWN_ELSTER_ID, "E-Kennung unbekannt, nicht abgleichbar"),
    FindingKind(LINE_MISMATCH, "Nr. im Vordruck weicht von der Struktur ab"),
)


def latest_reading(state: ModuleState, year: int) -> ProtocolReading | None:
    """Das zuletzt aufgenommene Protokoll des Jahrs.

    Maßgeblich ist `taken_in_at` seines Dokuments, bei Gleichstand die `id` des Protokolls.
    """
    taken = {d.address: d.taken_in_at for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [r for r in state.all(ProtocolReading) if r.year == year and r.document in taken]
    if not readings:
        return None

    return max(readings, key=lambda r: taken_order(taken[r.document], r.id))


def _field_findings(
    field: FormField, ref: ValueRef, value: ExposedValue, reading: ProtocolReading
) -> Iterator[Finding]:
    name = f"{field.name} ({field.elster_id})"
    lines = [line for line in reading.lines if line.elster_id == field.elster_id]
    if not lines:
        if value.amount.value == 0:
            return  # ELSTER überträgt leere Felder nicht; 0 und fehlendes Feld stimmen überein
        yield Finding(
            MISSING,
            Severity.WARNING,
            ref,
            f"{name}: Das Feld fehlt im Übertragungsprotokoll.",
            href=protocol_url(reading.id),
            fingerprint=fingerprint(field.elster_id, value.amount.value),
        )
        return
    first = protocol_url(reading.id, lines[0].data_name)
    expected = value.amount.value
    contents = [line.content for line in lines]
    transferred = field.read_protocol(contents)
    match transferred:
        case AmbiguousLines(count=count):
            yield Finding(
                AMBIGUOUS,
                Severity.WARNING,
                ref,
                f"{name}: Das Feld kommt {count}-mal im Protokoll vor; "
                "ein Vergleich ist nicht möglich.",
                href=first,
                fingerprint=fingerprint(field.elster_id, *contents),
            )
            return
        case NotANumber(content=content):
            text = f"Wert {field.show(expected)}, Protokoll „{content}“ ist keine Zahl."
        case _ if transferred != expected:
            text = field.explain_deviation(expected, transferred)
        case _:
            return
    yield Finding(
        DEVIATION,
        Severity.WARNING,
        ref,
        f"{name}: {text}",
        href=first,
        fingerprint=fingerprint(field.elster_id, expected, *contents),
    )


def _structure_findings(reading: ProtocolReading, structure: FormStructure) -> Iterator[Finding]:
    """Gegenprobe der Zeilen der Anlage im Protokoll gegen die Struktur des Jahres: eine E-Kennung
    ohne Feld in der Struktur (vermutlich fehlt eine gespeicherte Mein-ELSTER-Seite) und eine
    andere Nr. im Vordruck. Eine leere Nr. (Wiederholzeile) wird nicht verglichen."""
    seen: set[tuple[str, str]] = set()
    page = ""  # Seite des zuletzt gesehenen bekannten Felds: dort dürfte das unbekannte liegen
    known = {f.e_kennung: f for f in structure.fields}
    for line in reading.lines:
        if line.form != structure.form:
            continue
        field = known.get(line.elster_id)
        if field is not None:
            page = field.page
        if (line.elster_id, line.form_line) in seen:
            continue
        seen.add((line.elster_id, line.form_line))
        number = line.form_line or "–"
        name = f"Anlage {structure.form} Nr. {number}, {line.label} ({line.elster_id})"
        href = protocol_url(reading.id, line.data_name)
        if field is None:
            where = f"nach der Seite „{page}“" if page else "am Anfang"
            yield Finding(
                UNKNOWN_ELSTER_ID,
                Severity.NOTE,
                line.elster_id,
                f"{name}: E-Kennung fehlt in der Struktur {structure.year}, nicht abgleichbar; "
                f"vermutlich fehlt eine gespeicherte Mein-ELSTER-Seite {where}.",
                href=href,
                fingerprint=fingerprint(line.elster_id, structure.year),
            )
        elif line.form_line and field.line and line.form_line != field.line:
            yield Finding(
                LINE_MISMATCH,
                Severity.WARNING,
                line.elster_id,
                f"{name}: Das Protokoll nennt Nr. {line.form_line}, die Struktur {structure.year} "
                f"Nr. {field.line}.",
                href=href,
                fingerprint=fingerprint(line.elster_id, line.form_line, field.line),
            )


def protocol_findings(
    state: ModuleState,
    values: ValueSource,
    year: int,
    forms: Forms = FORMS,
    structures: Mapping[int, FormStructure] = STRUCTURES,
) -> list[Finding]:
    """Befunde des Abgleichs für das Jahr; ohne aufgenommenes Protokoll gibt es keinen Abgleich."""
    fields = forms.get(year)
    reading = latest_reading(state, year)
    if reading is None:
        return []
    found: list[Finding] = []
    if (structure := structures.get(year)) is not None:
        found.extend(_structure_findings(reading, structure))
    if fields is None:
        return found
    for field in fields:
        if not field.computed:
            continue  # kein Wert, also nichts zu vergleichen
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
                    href=protocol_url(reading.id),
                    fingerprint=fingerprint(field.key, field.label),
                )
            )
        elif isinstance(result, ExposedValue):  # sonst gibt es nichts zu vergleichen
            found.extend(_field_findings(field, ref, result, reading))
    return found
