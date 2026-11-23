"""Aussteller-Liste mit Jahresmatrix: je Aussteller und Steuerjahr ein Zeichen, dazu Filter und
Anzahlen (Spec 3.2; reine Funktionen, die Seite liest nur Abfrage und rendert).

Ein Dokument zählt für ein Jahr nach `belongs_to_year`; „erwartet“ folgt `expected_documents`:
ein Erwarteter Beleg ist für den Aussteller erwartet, wenn er im Jahr fällig ist und der Aussteller
ihn im Jahr oder im Vorjahr erfüllt hat (dieselbe Regel wie der Vorschlag `previous_year_issuer`).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from moarcoal.documents import belongs_to_year
from moarcoal.expected_documents import matching_documents, previous_year_issuer
from moarcoal.personal_details import own_issuer_first
from moarcoal.storage import Document, ExpectedDocument, Issuer, State, name_key
from moarcoal.storage.entries import referenced_addresses
from moarcoal.storage.sites import Sites

YEARS_SHOWN = 10


class Mark(Enum):
    """Das Zeichen einer Zelle: Wert ist der Name der Stufe der Statussprache."""

    PRESENT = "proven"  # ●  Belege da (und erwartete Belege erfüllt)
    PARTIAL = "assumed"  # ◐  erwartet, teils da
    MISSING = "error"  # ○  erwartet, fehlt
    NONE = "none"  # ·  keine Belege

    @property
    def symbol(self) -> str:
        return {"proven": "●", "assumed": "◐", "error": "○", "none": "·"}[self.value]

    @property
    def label(self) -> str:
        return {
            "proven": "Belege da",
            "assumed": "erwartet, teils da",
            "error": "erwartet, fehlt",
            "none": "keine Belege",
        }[self.value]


class IssuerFilter(Enum):
    ALL = "alle"
    NO_DOCUMENTS = "ohne-belege"
    PORTAL = "portal"


@dataclass(frozen=True)
class YearMark:
    """Eine Zelle der Jahresmatrix: das Zeichen, die Anzahl der Belege des Ausstellers im Jahr
    (nach `belongs_to_year`) und die im Jahr fehlenden erwarteten Belege."""

    year: int
    mark: Mark
    documents: int
    missing: tuple[ExpectedDocument, ...]


@dataclass(frozen=True)
class IssuerRow:
    issuer: Issuer
    documents: int  # verschiedene Dokumente, die zu mindestens einem gezeigten Jahr gehören
    marks: tuple[YearMark, ...]  # je gezeigtem Jahr
    recent_years_with_documents: bool  # Belege im Vorjahr oder in diesem Jahr


@dataclass(frozen=True)
class FilterCounts:
    all: int
    no_documents: int
    portal: int


def years_shown(this_year: int) -> list[int]:
    """Die gezeigten Steuerjahre, aufsteigend, das letzte ist das aktuelle."""
    return list(range(this_year - YEARS_SHOWN + 1, this_year + 1))


def _due(
    issuer: Issuer,
    year: int,
    own: list[Document],
    all_documents: list[Document],
    expected: list[ExpectedDocument],
) -> list[tuple[ExpectedDocument, bool]]:
    """Die für den Aussteller im Jahr erwarteten Belege, je mit „erfüllt von einem seiner
    Dokumente“."""
    return [
        (e, any(d in own for d in matching_documents(all_documents, e, year)))
        for e in expected
        if e.due_in(year)
        and (
            previous_year_issuer(all_documents, e, year) == issuer.address
            or any(d in own for d in matching_documents(all_documents, e, year))
        )
    ]


def _year_mark(
    issuer: Issuer,
    year: int,
    own: list[Document],
    all_documents: list[Document],
    expected: list[ExpectedDocument],
    in_year: list[Document],
) -> YearMark:
    due = _due(issuer, year, own, all_documents, expected)
    missing = tuple(e for e, done in due if not done)
    if not due:
        mark = Mark.PRESENT if in_year else Mark.NONE
    elif not missing:
        mark = Mark.PRESENT
    else:
        mark = Mark.PARTIAL if len(missing) < len(due) else Mark.MISSING
    return YearMark(year, mark, len(in_year), missing)


def issuer_rows(state: State, user: str, sites: Sites, this_year: int) -> list[IssuerRow]:
    """Alle Aussteller mit ihren Zeichen je Jahr, nach Anzahl der Belege der gezeigten Jahre
    absteigend, dann nach Name."""
    all_documents = [d for d in state.of_kind(Document) if d.owner == user]
    expected = [e for e in state.of_kind(ExpectedDocument) if e.owner == user]
    years = years_shown(this_year)
    rows: list[IssuerRow] = []
    for issuer in state.of_kind(Issuer):
        own = [d for d in all_documents if d.issuer == issuer.address]
        by_year = {y: [d for d in own if belongs_to_year(d, y, state, sites)] for y in years}
        marks = tuple(
            _year_mark(issuer, y, own, all_documents, expected, by_year[y]) for y in years
        )
        shown = {d.address for in_year in by_year.values() for d in in_year}
        recent = bool(by_year[this_year] or by_year[this_year - 1])
        rows.append(IssuerRow(issuer, len(shown), marks, recent))
    return sorted(rows, key=lambda r: (-r.documents, name_key(r.issuer.name), r.issuer.id))


def matches(issuer: Issuer, query: str) -> bool:
    """Ob die Suche Name oder einen weiteren Namen trifft."""
    needle = name_key(query)
    return any(needle in name_key(name) for name in (issuer.name, *issuer.aliases))


def search(rows: Iterable[IssuerRow], query: str) -> list[IssuerRow]:
    return [r for r in rows if matches(r.issuer, query)]


def counts(rows: list[IssuerRow]) -> FilterCounts:
    return FilterCounts(
        all=len(rows),
        no_documents=sum(1 for r in rows if not r.recent_years_with_documents),
        portal=sum(1 for r in rows if r.issuer.portal),
    )


def apply_filter(rows: list[IssuerRow], chosen: IssuerFilter) -> list[IssuerRow]:
    match chosen:
        case IssuerFilter.NO_DOCUMENTS:
            return [r for r in rows if not r.recent_years_with_documents]
        case IssuerFilter.PORTAL:
            return [r for r in rows if r.issuer.portal]
        case IssuerFilter.ALL:
            return rows


def parse_filter(text: str) -> IssuerFilter:
    """Der Filter aus der Adresse; Unbekanntes gilt als „alle“."""
    return next((f for f in IssuerFilter if f.value == text), IssuerFilter.ALL)


def own_first(rows: list[IssuerRow], own: Issuer | None) -> list[IssuerRow]:
    """Die Zeilen mit dem eigenen Aussteller (Angaben zur Person) an erster Stelle, falls er
    vorkommt; der Rest behält die Reihenfolge."""
    by_id = {r.issuer.id: r for r in rows}
    return [by_id[i.id] for i in own_issuer_first([r.issuer for r in rows], own)]


@dataclass(frozen=True)
class YearDocuments:
    """Die Belege eines Ausstellers in einem Jahr: seine Dokumente und die erwarteten Belege,
    die im Jahr fehlen."""

    year: int
    documents: tuple[Document, ...]
    missing: tuple[ExpectedDocument, ...]


@dataclass(frozen=True)
class IssuerDetail:
    """Die Belege eines Ausstellers: alle seine Dokumente, je Jahr absteigend (nur Jahre mit
    Dokumenten oder fehlenden erwarteten Belegen) und die Dokumente, die zu keinem Jahr gehören."""

    documents: int
    years: tuple[YearDocuments, ...]
    without_year: tuple[Document, ...]

    @property
    def years_with_documents(self) -> int:
        return sum(1 for y in self.years if y.documents)


def _candidate_years(state: State, sites: Sites, document: Document) -> set[int]:
    """Jahre, zu denen das Dokument gehören kann; entschieden wird mit `belongs_to_year`."""
    years: set[int] = set()
    if document.period_start is not None and document.period_end is not None:
        years.update(range(document.period_start.year, document.period_end.year + 1))
    site_year = sites.year_of(document.site)
    if site_year is not None:
        years.add(site_year)
    for entry in state.entries.values():
        year = getattr(entry, "year", None)
        if isinstance(year, int) and document.address in referenced_addresses(entry):
            years.add(year)
    return years


def issuer_detail(
    state: State, user: str, sites: Sites, issuer: Issuer, this_year: int
) -> IssuerDetail:
    all_documents = [d for d in state.of_kind(Document) if d.owner == user]
    expected = [e for e in state.of_kind(ExpectedDocument) if e.owner == user]
    own = [d for d in all_documents if d.issuer == issuer.address]
    candidates = set(years_shown(this_year))
    for d in own:
        candidates |= _candidate_years(state, sites, d)
    years: list[YearDocuments] = []
    for year in sorted(candidates, reverse=True):
        in_year = tuple(d for d in own if belongs_to_year(d, year, state, sites))
        missing = tuple(
            e for e, done in _due(issuer, year, own, all_documents, expected) if not done
        )
        if in_year or missing:
            years.append(YearDocuments(year, in_year, missing))
    placed = {d.address for y in years for d in y.documents}
    return IssuerDetail(
        documents=len(own),
        years=tuple(years),
        without_year=tuple(d for d in own if d.address not in placed),
    )
