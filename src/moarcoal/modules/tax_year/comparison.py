"""Abgleich der Felder der Anlage N mit Übertragungsprotokoll und Bescheid (Befunde).

Verglichen wird exakt und ohne Toleranz gegen den gerundeten Wert des Felds (das Steuerjahr rundet
nach Einheit und Richtung, siehe `fields`). Weicht das Protokoll nur durch Rundung ab, nennt der
Text Differenz und Richtung. Mehrere Zeilen derselben E-Kennung werden bei EUR-Feldern summiert;
bei Tagen und km sind sie mehrdeutig.

Der EStB wird gegen den Schnappschuss der Abgabe verglichen, nicht gegen den
aktuellen Wert: Er zeigt, wo das Finanzamt anders angesetzt hat als abgegeben. Nur bestätigte
Positionen gehen ein; berechnete Felder ohne Gegenstück im Schnappschuss bleiben ohne Abgleich.
"""

import datetime
from collections.abc import Iterator, Sequence
from decimal import Decimal

from moarcoal.modules.tax_year.anlage_n import FORMS, Forms
from moarcoal.modules.tax_year.assessment import ASSESSMENT_KEY
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.modules.tax_year.fields import AmbiguousLines, FormField, NotANumber
from moarcoal.proposals import document_url
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Document, Entry, FrozenValue, Occasion, Put, Snapshot
from moarcoal.values.calculation import ValueSource
from moarcoal.values.engine import Values
from moarcoal.values.findings import Finding, FindingKind, Severity, fingerprint
from moarcoal.values.model import ExposedValue, Period, ValueKey, ValueRef
from moarcoal.values.snapshots import (
    compare,
    freeze,
    frozen_time,
    latest_snapshots,
    outcome_text,
)

DEVIATION = "tax_year.protocol_deviation"
MISSING = "tax_year.protocol_missing"
AMBIGUOUS = "tax_year.protocol_ambiguous"
UNKNOWN_ELSTER_ID = "tax_year.protocol_unknown_elster_id"
SNAPSHOT_DEVIATION = "tax_year.snapshot_deviation"
ASSESSMENT_DEVIATION = "tax_year.assessment_deviation"
ASSESSMENT_NO_SNAPSHOT = "tax_year.assessment_no_snapshot"
MODULE_KEY = "tax_year"

FINDING_KINDS = (
    FindingKind(DEVIATION, "Übertragungsprotokoll weicht vom Wert ab"),
    FindingKind(MISSING, "Feld fehlt im Übertragungsprotokoll"),
    FindingKind(AMBIGUOUS, "Feld kommt im Übertragungsprotokoll mehrfach vor"),
    FindingKind(UNKNOWN_ELSTER_ID, "E-Kennung unbekannt, nicht abgleichbar"),
    FindingKind(SNAPSHOT_DEVIATION, "Abweichung zum Schnappschuss"),
    FindingKind(ASSESSMENT_DEVIATION, "Bescheid weicht vom Schnappschuss der Abgabe ab"),
    FindingKind(ASSESSMENT_NO_SNAPSHOT, "Kein Schnappschuss zum Abgleich mit dem Bescheid"),
)


def _taken_order(moment: datetime.datetime | None, entry_id: str) -> tuple[bool, float, str]:
    """Reihenfolge nach Aufnahmezeitpunkt (ohne Zeitpunkt zuerst), bei Gleichstand nach `id`."""
    return (moment is not None, moment.timestamp() if moment else 0.0, entry_id)


def latest_reading(state: ModuleState, year: int) -> ProtocolReading | None:
    """Das zuletzt aufgenommene Protokoll des Jahrs.

    Maßgeblich ist `taken_in_at` seines Dokuments, bei Gleichstand die `id` des Protokolls.
    """
    taken = {d.address: d.taken_in_at for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [r for r in state.all(ProtocolReading) if r.year == year and r.document in taken]
    if not readings:
        return None

    return max(readings, key=lambda r: _taken_order(taken[r.document], r.id))


def protocol_url(reading: ProtocolReading, data_name: str = "") -> str:
    """Seite des Protokolls, auf Wunsch mit Sprung zur Zeile."""
    base = f"/steuerjahr/uebertragungsprotokolle/{reading.id}"
    return f"{base}#{data_name}" if data_name else base


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
            fingerprint=fingerprint(field.elster_id, value.amount.value),
        )
        return
    first = protocol_url(reading, lines[0].data_name)
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


def protocol_findings(
    state: ModuleState, values: ValueSource, year: int, forms: Forms = FORMS
) -> list[Finding]:
    """Befunde des Abgleichs für das Jahr; ohne aufgenommenes Protokoll gibt es keinen Abgleich."""
    fields = forms.get(year)
    reading = latest_reading(state, year)
    if fields is None or reading is None:
        return []
    found: list[Finding] = []
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
                    href=protocol_url(reading),
                    fingerprint=fingerprint(field.key, field.label),
                )
            )
        elif isinstance(result, ExposedValue):  # sonst gibt es nichts zu vergleichen
            found.extend(_field_findings(field, ref, result, reading))
    return found


def anlage_n_url(year: int) -> str:
    return f"/steuerjahr/anlage-n/{year}"


def latest_snapshot(state: ModuleState, year: int) -> Snapshot | None:
    """Der neueste Schnappschuss der Abgabe des Jahrs, den dieses Modul ausgelöst hat."""
    time = frozen_time(Period.year(year))
    found = [s for s in state.snapshots() if s.occasion is Occasion.FILING and s.time == time]
    return latest_snapshots(found)[-1] if found else None


def describe_frozen(field: FormField, frozen: FrozenValue) -> str:
    """Der eingefrorene Wert eines Felds als Klartext, ganze Euro ohne Cent."""
    if frozen.outcome == "amount" and frozen.amount is not None:
        return field.show(frozen.amount.value)
    return outcome_text(frozen)


def snapshot_findings(
    state: ModuleState, values: ValueSource, year: int, forms: Forms = FORMS
) -> list[Finding]:
    """Warnung je Feld, dessen aktueller Wert vom eingefrorenen der Abgabe abweicht; verglichen
    wird mit dem neuesten Schnappschuss des Jahrs."""
    fields = forms.get(year)
    snapshot = latest_snapshot(state, year)
    if fields is None or snapshot is None:
        return []
    deviations = compare(snapshot, values)
    period = Period.year(year)
    found: list[Finding] = []
    for field in fields:
        mine = [
            d for d in deviations if d.ref.key == field.key and d.ref.time == frozen_time(period)
        ]
        if not mine:
            continue
        name = f"Anlage N Nr. {field.form_line}, {field.label}"
        taken = snapshot.taken_at.strftime("%d.%m.%Y")
        texts = [d.text_with(lambda amount, f=field: f.show(amount.value)) for d in mine]
        found.append(
            Finding(
                SNAPSHOT_DEVIATION,
                Severity.WARNING,
                ValueRef(field.key, state.user, period, None),
                f"{name}: Abweichung zum Schnappschuss bei Abgabe am {taken}. " + "; ".join(texts),
                href=anlage_n_url(year),
                fingerprint=fingerprint(snapshot.id, field.key, *texts),
            )
        )
    return found


def assessment_amounts(
    state: ModuleState, document: Document, fields: Sequence[FormField]
) -> dict[ValueKey, Decimal]:
    """Der Betrag laut Bescheid je Feld, dessen Positionen alle bestätigt sind.

    Ein Feld mit mehreren Positionen bekommt ihre Summe; eine bestätigte leere Position zählt 0,
    ein gedrucktes Minus nicht (Abzüge stehen mit Minus; Positionen mit Vorzeichen sind noch nicht
    zugeordnet). Unbestätigte Positionen gehen nicht ein, ebenso wenig ein Feld, dessen bestätigter
    Inhalt keine Zahl ist.
    """
    confirmed = state.confirmed_fields(document)
    amounts: dict[ValueKey, Decimal] = {}
    for field in fields:
        if not field.assessment or not all(key in confirmed for key in field.assessment):
            continue
        contents = [confirmed[key][0] for key in field.assessment]
        numbers = [c for c in contents if isinstance(c, Decimal)]
        if len(numbers) + contents.count(None) == len(contents):
            amounts[field.key] = sum((abs(n) for n in numbers), start=Decimal(0))
    return amounts


def current_assessment(
    state: ModuleState, year: int, fields: Sequence[FormField]
) -> tuple[Document, dict[ValueKey, Decimal]] | None:
    """Der neueste EStB des Jahrs, zu dem schon Positionen bestätigt sind, mit
    den Beträgen je Feld. Ein neu aufgenommener, noch unbestätigter Bescheid verdrängt den
    bestätigten nicht."""
    found = [
        d
        for d in state.documents(ASSESSMENT_KEY)
        if d.period_start is not None and d.period_start.year == year
    ]
    for document in sorted(found, key=lambda d: _taken_order(d.taken_in_at, d.id), reverse=True):
        if amounts := assessment_amounts(state, document, fields):
            return document, amounts
    return None


def _frozen_amount(snapshot: Snapshot, field: FormField, year: int) -> Decimal | None:
    """Der eingefrorene Betrag des Felds; entfällt er, gilt 0, ist er unberechenbar, fehlt er."""
    time = frozen_time(Period.year(year))
    for value in snapshot.values:
        if value.requested and value.ref.key == field.key and value.ref.time == time:
            if value.outcome == "amount" and value.amount is not None:
                return value.amount.value
            return Decimal(0) if value.outcome == "not_applicable" else None
    return None


def assessment_findings(state: ModuleState, year: int, forms: Forms = FORMS) -> list[Finding]:
    """Befunde des Bescheid-Abgleichs: je Feld, das der Bescheid anders ansetzt als der
    Schnappschuss der Abgabe. Ohne Schnappschuss gibt es keinen Abgleich, nur einen Hinweis."""
    fields = forms.get(year)
    current = None if fields is None else current_assessment(state, year, fields)
    if fields is None or current is None:
        return []
    document, amounts = current
    snapshot = latest_snapshot(state, year)
    if snapshot is None:
        if not any(f.computed and f.key in amounts for f in fields):
            return []  # nichts Bestätigtes, das sich je abgleichen ließe
        return [
            Finding(
                ASSESSMENT_NO_SNAPSHOT,
                Severity.NOTE,
                document.address,
                f"Zum EStB {year} gibt es keinen Schnappschuss der Abgabe; "
                "ein Abgleich ist nicht möglich.",
                href=document_url(document),
                fingerprint=fingerprint(document.id),
            )
        ]
    period = Period.year(year)
    found: list[Finding] = []
    for field in fields:
        if field.key not in amounts:
            continue
        printed = amounts[field.key]
        frozen = _frozen_amount(snapshot, field, year)
        if frozen is None or field.matches_assessment(frozen, printed):
            continue
        taken = snapshot.taken_at.strftime("%d.%m.%Y")
        found.append(
            Finding(
                ASSESSMENT_DEVIATION,
                Severity.WARNING,
                ValueRef(field.key, state.user, period, None),
                f"Anlage N Nr. {field.form_line}, {field.label}: Laut Bescheid "
                f"{field.show(printed)}, bei Abgabe am {taken} {field.show(frozen)}.",
                href=document_url(document),
                fingerprint=fingerprint(document.id, field.key, printed, frozen),
            )
        )
    return found


def module_findings(
    state: ModuleState, values: ValueSource, year: int, forms: Forms = FORMS
) -> list[Finding]:
    """Alle Befunde des Steuerjahrs: Abgleich mit dem Protokoll, Abweichung zum Schnappschuss und
    Abgleich des Bescheids mit dem Schnappschuss."""
    return [
        *protocol_findings(state, values, year, forms),
        *snapshot_findings(state, values, year, forms),
        *assessment_findings(state, year, forms),
    ]


def snapshot_on_filing(
    document: Document, entries: Sequence[Entry], values: Values, forms: Forms = FORMS
) -> Sequence[Change]:
    """Ergänzung beim Aufnehmen eines Protokolls (Spec 3.6 Punkt 8): friert die Werte der Felder
    des Jahrs als Schnappschuss der Abgabe ein. Jahre ohne Felder (vor 2025): keiner."""
    reading = next((e for e in entries if isinstance(e, ProtocolReading)), None)
    fields = None if reading is None else forms.get(reading.year)
    if reading is None or not fields:
        return []
    period = Period.year(reading.year)
    snapshot = Snapshot(
        owner=document.owner,
        occasion=Occasion.FILING,
        taken_at=document.taken_in_at or datetime.datetime.now(datetime.UTC),
        module=MODULE_KEY,
        document=document.address,
        time=frozen_time(period),
        values=freeze(values, document.owner, [f.key for f in fields if f.computed], period),
    )
    return [Put(snapshot)]
