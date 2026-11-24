"""Die Anlage-Ansicht: was eine Seite der Anlage zeigt, als reine Funktion.

`anlage_view` macht aus dem Stand des Moduls, den Werten und den Befunden die Zeilen des Felds und
die Sonderteile einer Seite der Anlage. Sie liest nichts aus der Anfrage und rendert nichts: die
Route liest, ruft sie auf und gibt das Ergebnis an die Vorlage (Prinzip 4). Die Vorlage verzweigt
nur nach der Form des Inhalts einer Zeile (`shape`).
"""

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
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
from moarcoal.values.model import Period, ValueKey, ValueRef, ValueResult

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


@dataclass(frozen=True)
class _Sources:
    """Was die Zeilen jeder Seite der Anlage brauchen, einmal je Anlage aus dem Stand gelesen:
    Schnappschuss, gedruckte Werte des EStB, Inhalt des Protokolls, Texte und Gründe aus der
    Person."""

    snapshot: Snapshot | None
    printed: dict[ValueKey, Decimal]
    transferred: dict[str, str] | None
    texts: dict[str, str]
    reasons: dict[str, str]

    @classmethod
    def read(cls, state: ModuleState, year_anlage: YearAnlage) -> "_Sources":
        year = year_anlage.year
        assessment = current_assessment(state, year, year_anlage.fields)
        reading = latest_reading(state, year)
        return cls(
            snapshot=latest_snapshot(state, year),
            printed={} if assessment is None else assessment[1],
            transferred=None
            if reading is None
            else protocol_contents(reading, year_anlage.structure),
            texts=field_texts(state, year_anlage.fields, year),
            reasons=field_reasons(state, year_anlage.fields, year),
        )


def _rows(
    state: ModuleState,
    values: ValueSource,
    findings: Sequence[Finding],
    hidden: Collection[Finding],
    year: int,
    page: FormPage,
    sources: _Sources,
) -> list[FieldRow]:
    """Die Zeilen der Seite mit Inhalt, Gegenproben und Stufe; ohne Links zum Erfassen (die setzt
    `anlage_view`, die Stufe braucht sie nicht)."""
    frozen: dict[str, str] | None = None
    if sources.snapshot is not None:
        frozen = {
            v.ref.key: describe_frozen(row.field, v)
            for row in page.rows
            for v in sources.snapshot.values
            if v.requested and v.ref.key == row.field.key
        }
    period = Period.year(year)
    rows: list[FieldRow] = []
    for row in page.rows:
        field = row.field
        text = sources.texts.get(field.elster_id)
        content: RowContent
        match field.kind:
            case Computed():
                content = ValueContent(
                    values.get(field.key, state.user, period), field.whole_euros, ()
                )
            case TypedInput() as typed:
                entry = current_input(state, year, field)
                content = InputContent(typed, entry.content if entry else None)
            case TextSource():
                content = TextContent(text, sources.reasons.get(field.elster_id))
            case NotComputed():
                content = NoContent()
        checks = field_checks(
            field,
            transferred=sources.transferred,
            frozen=frozen,
            printed=sources.printed,
            findings=findings,
            hidden=hidden,
            content=text,
        )
        match content:
            case ValueContent():
                grading = grade_row(content.result, checks, filled=False)
            case InputContent():
                grading = grade_row(None, checks, filled=bool(content.saved))
            case TextContent():
                grading = grade_row(None, checks, filled=bool(content.text))
            case NoContent():
                grading = grade_row(None, checks, filled=False)
        rows.append(FieldRow(field, row.headings, row.structure.unit, content, checks, grading))
    return rows


def _with_links(row: FieldRow, captures: Captures) -> FieldRow:
    """Die Zeile mit den Links zum Erfassen dessen, woraus ihr Wert rechnet."""
    if not isinstance(row.content, ValueContent):
        return row
    links = tuple(captures(foreign_refs(row.content.result)))
    return replace(row, content=replace(row.content, links=links))


def anlage_view(
    state: ModuleState,
    values: ValueSource,
    findings: Sequence[Finding],
    captures: Captures,
    year_anlage: YearAnlage,
    slug: str | None,
    params: PageParams,
    hidden: Collection[Finding] = (),
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
    sources = _Sources.read(state, year_anlage)
    rows = _rows(state, values, findings, hidden, year, page, sources)
    first = page == year_anlage.pages[0]
    parts = tuple(
        (part, part.data(state, year, params))
        for part in year_anlage.parts
        if first or part.place is not Place.TOP
    )
    return AnlageView(
        year_anlage, page, tuple(_with_links(r, captures) for r in rows), parts, sources.snapshot
    )


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
    hidden: Collection[Finding] = (),
) -> AnlageGrading:
    """Die Stufe der Seiten der Anlage und der Anlage, aus denselben Zeilen wie die Seiten selbst
    (`_rows`), also dieselbe Stufe wie der Statusstreifen."""
    sources = _Sources.read(state, year_anlage)
    pages = {
        page.slug: combine(
            r.grading
            for r in _rows(state, values, findings, hidden, year_anlage.year, page, sources)
        )
        for page in year_anlage.pages
    }
    return AnlageGrading(combine(pages.values()), pages)
