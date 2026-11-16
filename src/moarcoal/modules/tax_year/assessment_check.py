"""Abgleich des EStB mit dem Schnappschuss der Abgabe (Befunde).

Der EStB wird gegen den Schnappschuss der Abgabe verglichen, nicht gegen den
aktuellen Wert: Er zeigt, wo das Finanzamt anders angesetzt hat als abgegeben. Nur bestätigte
Positionen gehen ein; berechnete Felder ohne Gegenstück im Schnappschuss bleiben ohne Abgleich.
"""

from collections.abc import Sequence
from decimal import Decimal

from moarcoal.modules.tax_year.anlage_n import FORMS
from moarcoal.modules.tax_year.assessment import ASSESSMENT_KEY
from moarcoal.modules.tax_year.entries import taken_order
from moarcoal.modules.tax_year.fields import FormField, Forms
from moarcoal.modules.tax_year.snapshot_check import latest_snapshot
from moarcoal.registration import ModuleState
from moarcoal.storage import Document, Snapshot
from moarcoal.values.findings import Finding, FindingKind, Severity, fingerprint
from moarcoal.values.model import Period, ValueKey, ValueRef
from moarcoal.values.snapshots import frozen_time
from moarcoal.web.links import document_url

ASSESSMENT_DEVIATION = "tax_year.assessment_deviation"
ASSESSMENT_NO_SNAPSHOT = "tax_year.assessment_no_snapshot"

FINDING_KINDS = (
    FindingKind(ASSESSMENT_DEVIATION, "EStB weicht vom Schnappschuss der Abgabe ab"),
    FindingKind(ASSESSMENT_NO_SNAPSHOT, "Kein Schnappschuss zum Abgleich mit dem EStB"),
)


def assessment_amounts(
    state: ModuleState, document: Document, fields: Sequence[FormField]
) -> dict[ValueKey, Decimal]:
    """Der Betrag laut EStB je Feld, dessen Positionen alle bestätigt sind.

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
    den Beträgen je Feld. Ein neu aufgenommener, noch unbestätigter EStB verdrängt den
    bestätigten nicht."""
    found = [
        d
        for d in state.documents(ASSESSMENT_KEY)
        if d.period_start is not None and d.period_start.year == year
    ]
    for document in sorted(found, key=lambda d: taken_order(d.taken_in_at, d.id), reverse=True):
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
    """Befunde des EStB-Abgleichs: je Feld, das der EStB anders ansetzt als der
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
                href=document_url(document.id),
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
                f"{field.name}: Laut EStB "
                f"{field.show(printed)}, bei Abgabe am {taken} {field.show(frozen)}.",
                href=document_url(document.id),
                fingerprint=fingerprint(document.id, field.key, printed, frozen),
            )
        )
    return found
