"""Die Anlage-Ansicht: was eine Seite der Anlage zeigt, als reine Funktion.

`anlage_view` macht aus dem Stand des Moduls, den Werten und den Befunden die Zeilen des Felds und
die Sonderteile einer Seite der Anlage. Sie liest nichts aus der Anfrage und rendert nichts: die
Route liest, ruft sie auf und gibt das Ergebnis an die Vorlage (Prinzip 4). Die Vorlage verzweigt
nur nach der Form des Inhalts einer Zeile (`shape`).
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from moarcoal.modules.tax_year.anlagen import YearAnlage, protocol_contents
from moarcoal.modules.tax_year.assessment_check import current_assessment
from moarcoal.modules.tax_year.capture import foreign_refs
from moarcoal.modules.tax_year.field_checks import FieldCheck, field_checks
from moarcoal.modules.tax_year.fields import (
    Computed,
    FormField,
    NotComputed,
    TextSource,
    TypedInput,
)
from moarcoal.modules.tax_year.inputs import current_input
from moarcoal.modules.tax_year.person_input import field_reasons, field_texts
from moarcoal.modules.tax_year.protocol_check import latest_reading
from moarcoal.modules.tax_year.snapshot_check import describe_frozen, latest_snapshot
from moarcoal.modules.tax_year.special_parts import PageParams, Place, SpecialPart
from moarcoal.modules.tax_year.stage import Grading, combine, grade_row
from moarcoal.modules.tax_year.structure import FormPage
from moarcoal.registration import ModuleState
from moarcoal.storage import Snapshot
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding
from moarcoal.values.model import Period, ValueRef, ValueResult

type Captures = Callable[[Iterable[ValueRef]], list[tuple[str, str]]]
"""Die Links zum Erfassen zu den fremden Werten eines Ergebnisses (Beschriftung, Adresse); die
Route bindet sie an die Module."""


@dataclass(frozen=True)
class ValueContent:
    """Inhalt der Zeile eines berechneten Felds: das Ergebnis (Betrag, entfällt, noch nicht
    berechenbar) und die Links zum Erfassen dessen, woraus es rechnet."""

    shape: ClassVar[str] = "value"
    result: ValueResult
    whole_euros: bool
    links: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class InputContent:
    """Inhalt der Zeile eines Eintippfelds: die Art des Felds und der gespeicherte Text."""

    shape: ClassVar[str] = "input"
    typed: TypedInput
    saved: str | None


@dataclass(frozen=True)
class TextContent:
    """Inhalt der Zeile eines Felds mit Text: der Text aus der Person; fehlt er, vielleicht mit
    dem Grund, warum er trotz Angaben nicht berechenbar ist."""

    shape: ClassVar[str] = "text"
    text: str | None
    reason: str | None


@dataclass(frozen=True)
class NoContent:
    """Inhalt der Zeile eines Felds, das MoarCoal noch nicht berechnet: keiner."""

    shape: ClassVar[str] = "none"


type RowContent = ValueContent | InputContent | TextContent | NoContent


@dataclass(frozen=True)
class FieldRow:
    """Die Zeile des Felds auf der Seite der Anlage: das Feld, die Überschriften, die hier neu
    beginnen, die Einheit aus der Struktur, der Inhalt je Art und die Gegenproben."""

    field: FormField
    headings: tuple[str, ...]
    unit: str
    content: RowContent
    checks: tuple[FieldCheck, ...]
    grading: Grading


@dataclass(frozen=True)
class AnlageView:
    """Eine Seite der Anlage, wie die Vorlage sie zeigt: die Anlage im Jahr, die Seite, ihre Zeilen,
    die Sonderteile mit ihren Daten (an ihrer Stelle) und der Schnappschuss der Abgabe."""

    anlage: YearAnlage
    page: FormPage
    rows: tuple[FieldRow, ...]
    parts: tuple[tuple[SpecialPart, object], ...]
    snapshot: Snapshot | None

    @property
    def grading(self) -> Grading:
        """Die Stufe der Seite: die schlechteste Stufe ihrer Zeilen (dieselbe wie im Baum)."""
        return combine(row.grading for row in self.rows)


def anlage_view(
    state: ModuleState,
    values: ValueSource,
    findings: Sequence[Finding],
    captures: Captures,
    year_anlage: YearAnlage,
    slug: str | None,
    params: PageParams,
) -> AnlageView | None:
    """Die Seite `slug` der Anlage (ohne: ihre erste); `None`, wenn sie sie nicht hat.

    Protokoll, Schnappschuss und EStB liest sie aus dem Stand, die Werte aus `values`, die Befunde
    der Gegenproben ordnet sie den Feldern zu. `captures` sagt, wohin das Erfassen führt.
    `year_anlage` bekommt sie übergeben; sie schlägt die Anlage nicht selbst nach.
    """
    year = year_anlage.year
    page = next((p for p in year_anlage.pages if slug is None or p.slug == slug), None)
    if page is None:
        return None
    snapshot = latest_snapshot(state, year)
    assessment = current_assessment(state, year, year_anlage.fields)
    printed = {} if assessment is None else assessment[1]
    frozen: dict[str, str] | None = None
    if snapshot is not None:
        frozen = {
            v.ref.key: describe_frozen(row.field, v)
            for row in page.rows
            for v in snapshot.values
            if v.requested and v.ref.key == row.field.key
        }
    reading = latest_reading(state, year)
    transferred = None if reading is None else protocol_contents(reading, year_anlage.structure)
    texts = field_texts(state, year_anlage.fields, year)
    reasons = field_reasons(state, year_anlage.fields, year)
    period = Period.year(year)
    rows: list[FieldRow] = []
    for row in page.rows:
        field = row.field
        text = texts.get(field.elster_id)
        content: RowContent
        match field.kind:
            case Computed():
                result = values.get(field.key, state.user, period)
                links = tuple(captures(foreign_refs(result)))
                content = ValueContent(result, field.whole_euros, links)
            case TypedInput() as typed:
                entry = current_input(state, year, field)
                content = InputContent(typed, entry.content if entry else None)
            case TextSource():
                content = TextContent(text, reasons.get(field.elster_id))
            case NotComputed():
                content = NoContent()
        checks = field_checks(
            field,
            transferred=transferred,
            frozen=frozen,
            printed=printed,
            findings=findings,
            content=text,
        )
        result = content.result if isinstance(content, ValueContent) else None
        filled = bool(
            content.saved
            if isinstance(content, InputContent)
            else content.text
            if isinstance(content, TextContent)
            else None
        )
        grading = grade_row(result, checks, filled)
        rows.append(FieldRow(field, row.headings, row.structure.unit, content, checks, grading))
    first = page == year_anlage.pages[0]
    parts = tuple(
        (part, part.data(state, year, params))
        for part in year_anlage.parts
        if first or part.place is not Place.TOP
    )
    return AnlageView(year_anlage, page, tuple(rows), parts, snapshot)


@dataclass(frozen=True)
class AnlageGrading:
    """Die Stufe einer Anlage im Baum der Übersicht: je Seite (nach Adressteil) und über alle."""

    whole: Grading
    pages: dict[str, Grading]


def grade_anlage(
    state: ModuleState,
    values: ValueSource,
    findings: Sequence[Finding],
    year_anlage: YearAnlage,
) -> AnlageGrading:
    """Die Stufe der Seiten der Anlage und der Anlage, aus denselben Zeilen wie die Seiten selbst
    (`anlage_view`), also dieselbe Stufe wie der Statusstreifen."""
    pages: dict[str, Grading] = {}
    for page in year_anlage.pages:
        shown = anlage_view(
            state, values, findings, _no_links, year_anlage, page.slug, PageParams("", None)
        )
        if shown is not None:
            pages[page.slug] = shown.grading
    return AnlageGrading(combine(pages.values()), pages)


def _no_links(refs: Iterable[ValueRef]) -> list[tuple[str, str]]:
    return []
