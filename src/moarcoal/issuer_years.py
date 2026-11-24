"""Aussteller-Liste mit Jahresmatrix: je Aussteller und Steuerjahr ein Zeichen, dazu Filter und
Anzahlen (Spec 3.2; reine Funktionen, die Seite liest nur Abfrage und rendert).

Ein Dokument zählt für ein Jahr nach `years_of_document`; „erwartet“ folgt `expected_documents`:
ein Erwarteter Beleg ist für den Aussteller erwartet, wenn er im Jahr fällig ist und der Aussteller
ihn im Jahr oder im Vorjahr erfüllt hat (dieselbe Regel wie der Vorschlag `previous_year_issuer`).
"""

from dataclasses import dataclass
from enum import Enum

from moarcoal.documents import DocumentYears, years_of_document
from moarcoal.expected_documents import matching_documents, previous_year_issuer
from moarcoal.storage import (
    Document,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    State,
    name_key,
)
from moarcoal.storage.sites import Sites

YEARS_SHOWN = 10


class Mark(Enum):
    """Das Zeichen einer Zelle der Jahresmatrix. Jedes trägt die Art der Statussprache (Farbe),
    das Zeichen für die Legende und das Wort; fehlende erwartete Belege sind gelb wie in der
    Stufe des Steuerjahrs."""

    PRESENT = ("proven", "●", "Belege da")  # Belege da (und erwartete Belege erfüllt)
    PARTIAL = ("warning", "◐", "erwartet, teils da")
    MISSING = ("warning", "○", "erwartet, fehlt")
    NONE = ("none", "·", "keine Belege")

    art: str
    symbol: str
    label: str

    def __init__(self, art: str, symbol: str, label: str) -> None:
        self.art = art
        self.symbol = symbol
        self.label = label


class IssuerFilter(Enum):
    """Ein Filter der Aussteller-Liste; der Wert steht in der Adresse."""

    ALL = "alle"
    NO_DOCUMENTS = "ohne-belege"
    PORTAL = "portal"

    @classmethod
    def parse(cls, text: str) -> "IssuerFilter":
        """Der Filter aus der Adresse; Unbekanntes gilt als „alle“."""
        return next((f for f in cls if f.value == text), cls.ALL)


@dataclass(frozen=True)
class YearMark:
    """Eine Zelle der Jahresmatrix: das Zeichen, die Anzahl der Belege des Ausstellers im Jahr
    und die im Jahr fehlenden erwarteten Belege."""

    year: int
    mark: Mark
    documents: int
    missing: tuple[ExpectedDocument, ...]


@dataclass(frozen=True)
class IssuerRow:
    issuer: Issuer
    documents: int  # verschiedene Dokumente, die zu mindestens einem gezeigten Jahr gehören
    marks: tuple[YearMark, ...]  # je gezeigtem Jahr
    documents_lately: bool  # Belege im Vorjahr oder in diesem Jahr


@dataclass(frozen=True)
class FilterCounts:
    all: int
    no_documents: int
    portal: int


def years_shown(this_year: int) -> list[int]:
    """Die gezeigten Steuerjahre, aufsteigend, das letzte ist das aktuelle."""
    return list(range(this_year - YEARS_SHOWN + 1, this_year + 1))


@dataclass(frozen=True)
class _Holdings:
    """Was Liste und Detail gleich brauchen: die Dokumente und Erwarteten Belege des Nutzers und
    die Jahre je Dokument, einmal gelesen."""

    documents: list[Document]
    expected: list[ExpectedDocument]
    years: dict[EntryAddress, DocumentYears]

    @classmethod
    def of(cls, state: State, user: str, sites: Sites) -> "_Holdings":
        documents = [d for d in state.of_kind(Document) if d.owner == user]
        return cls(
            documents,
            [e for e in state.of_kind(ExpectedDocument) if e.owner == user],
            {d.address: years_of_document(d, state, sites) for d in documents},
        )

    def own(self, issuer: Issuer) -> list[Document]:
        return [d for d in self.documents if d.issuer == issuer.address]

    def in_year(self, own: list[Document], year: int) -> list[Document]:
        return [d for d in own if year in self.years[d.address]]

    def due(
        self, issuer: Issuer, own: list[Document], year: int
    ) -> list[tuple[ExpectedDocument, bool]]:
        """Die für den Aussteller im Jahr erwarteten Belege, je mit „erfüllt von einem seiner
        Dokumente“."""
        found: list[tuple[ExpectedDocument, bool]] = []
        for e in self.expected:
            if not e.due_in(year):
                continue
            done = any(d in own for d in matching_documents(self.documents, e, year))
            if done or previous_year_issuer(self.documents, e, year) == issuer.address:
                found.append((e, done))
        return found

    def missing(self, issuer: Issuer, own: list[Document], year: int) -> list[ExpectedDocument]:
        return [e for e, done in self.due(issuer, own, year) if not done]


def _year_mark(
    holdings: _Holdings, issuer: Issuer, own: list[Document], year: int, in_year: list[Document]
) -> YearMark:
    due = holdings.due(issuer, own, year)
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
    holdings = _Holdings.of(state, user, sites)
    years = years_shown(this_year)
    rows: list[IssuerRow] = []
    for issuer in state.of_kind(Issuer):
        own = holdings.own(issuer)
        by_year = {y: holdings.in_year(own, y) for y in years}
        marks = tuple(_year_mark(holdings, issuer, own, y, by_year[y]) for y in years)
        shown = {d.address for in_year in by_year.values() for d in in_year}
        lately = bool(by_year[this_year] or by_year[this_year - 1])
        rows.append(IssuerRow(issuer, len(shown), marks, lately))
    return sorted(rows, key=lambda r: (-r.documents, name_key(r.issuer.name), r.issuer.id))


def matches(issuer: Issuer, query: str) -> bool:
    """Ob die Suche Name oder einen weiteren Namen trifft."""
    needle = name_key(query)
    return any(needle in name_key(name) for name in (issuer.name, *issuer.aliases))


def _passes(row: IssuerRow, chosen: IssuerFilter) -> bool:
    match chosen:
        case IssuerFilter.NO_DOCUMENTS:
            return not row.documents_lately
        case IssuerFilter.PORTAL:
            return bool(row.issuer.portal)
        case IssuerFilter.ALL:
            return True


def listed(
    rows: list[IssuerRow], query: str, chosen: IssuerFilter, own: Issuer | None
) -> tuple[list[IssuerRow], FilterCounts]:
    """Die gezeigte Liste: die Zeilen, die die Suche trifft und der Filter durchlässt, der eigene
    Aussteller (Angaben zur Person) zuerst, sonst in der Reihenfolge von `rows`; dazu die Anzahlen
    je Filter innerhalb der Suche."""
    searched = [r for r in rows if matches(r.issuer, query)]
    shown = [r for r in searched if _passes(r, chosen)]
    if own is not None:
        shown.sort(key=lambda r: r.issuer.id != own.id)  # stabil: Rest behält die Reihenfolge

    def n(chosen: IssuerFilter) -> int:
        return sum(1 for r in searched if _passes(r, chosen))

    found = FilterCounts(n(IssuerFilter.ALL), n(IssuerFilter.NO_DOCUMENTS), n(IssuerFilter.PORTAL))
    return shown, found


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


def issuer_detail(
    state: State, user: str, sites: Sites, issuer: Issuer, this_year: int
) -> IssuerDetail:
    holdings = _Holdings.of(state, user, sites)
    own = holdings.own(issuer)
    candidates = set(years_shown(this_year)).union(*(holdings.years[d.address].years for d in own))
    years: list[YearDocuments] = []
    for year in sorted(candidates, reverse=True):
        in_year = tuple(holdings.in_year(own, year))
        missing = tuple(holdings.missing(issuer, own, year))
        if in_year or missing:
            years.append(YearDocuments(year, in_year, missing))
    return IssuerDetail(
        documents=len(own),
        years=tuple(years),
        without_year=tuple(d for d in own if not holdings.years[d.address]),
    )
