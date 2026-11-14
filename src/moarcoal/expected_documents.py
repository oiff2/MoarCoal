"""Erwartete Belege: welches Dokument für ein Jahr erfüllt, was fehlt (docs/grundgeruest.md, 3.6).

Ein Erwarteter Beleg ist für ein Jahr erfüllt, sobald ein Dokument des Nutzers mit seiner
Dokumentart und einem Bezugszeitraum, der in dieses Jahr fällt, da ist; ob dessen Vorschlag
bestätigt ist, spielt keine Rolle (3.6, Punkt 7).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from moarcoal.storage import Document, EntryAddress, ExpectedDocument, State
from moarcoal.values.findings import Finding, Severity, fingerprint

PENDING = "expected_document_pending"
DUPLICATE = "expected_document_duplicate"
HREF = "/belege/erwartet"


def matching_documents(
    documents: list[Document], expected: ExpectedDocument, year: int
) -> list[Document]:
    """Dokumente der Dokumentart, deren Bezugszeitraum das Jahr berührt; nach Adresse sortiert."""
    found = [
        d for d in documents if d.document_kind == expected.document_kind and d.touches_year(year)
    ]
    return sorted(found, key=lambda d: str(d.address))


@dataclass(frozen=True)
class YearDocuments:
    """Stand eines Erwarteten Belegs für ein Jahr: die passenden Dokumente (keins: ausstehend)."""

    year: int
    documents: tuple[Document, ...]

    @property
    def pending(self) -> bool:
        return not self.documents


def statuses(
    documents: list[Document], expected: ExpectedDocument, through: int
) -> list[YearDocuments]:
    """Der Stand je Jahr von Beginn bis Ende, bei offenem Ende bis `through` (mindestens Beginn)."""
    last = expected.end_year if expected.end_year is not None else max(through, expected.start_year)
    return [
        YearDocuments(year, tuple(matching_documents(documents, expected, year)))
        for year in range(expected.start_year, last + 1)
    ]


def pending_for(
    documents: list[Document], expecteds: list[ExpectedDocument], kind: str, year: int
) -> list[ExpectedDocument]:
    """Die Erwarteten Belege, die ein Dokument dieser Art für dieses Jahr erfüllen würde: gleiche
    Art, Jahr fällig und noch ausstehend (nach derselben Regel wie `statuses`)."""
    return [
        e
        for e in expecteds
        if e.document_kind == kind and e.due_in(year) and not matching_documents(documents, e, year)
    ]


def previous_year_issuer(
    documents: list[Document], expected: ExpectedDocument, year: int
) -> EntryAddress | None:
    """Vorschlag: Aussteller des Dokuments, das den Beleg im Vorjahr erfüllt (gleiche Regel).

    Berechnet, nicht gespeichert, und ohne Einfluss auf die Erfüllung. Kein Vorschlag, wenn das
    Vorjahr vor dem Beginn liegt, offen ist oder kein erfüllendes Dokument einen Aussteller trägt.
    """
    if year - 1 < expected.start_year:
        return None
    return next(
        (d.issuer for d in matching_documents(documents, expected, year - 1) if d.issuer), None
    )


def expected_name(expected: ExpectedDocument, titles: Mapping[str, str]) -> str:
    title = titles.get(expected.document_kind, expected.document_kind)
    return f"{title} ({expected.description})" if expected.description else title


def expected_document_findings(
    state: State, user: str, year: int, titles: Mapping[str, str]
) -> list[Finding]:
    """Hinweise für `year`: Beleg ausstehend; mehrere passende Dokumente (mögliche Dublette).

    Das Ziel ist die Adresse mit dem Jahr (`<Adresse>@<Jahr>`), je Jahr ein eigener Befund. Der
    Fingerabdruck von „ausstehend“ nennt Dokumentart und Beschreibung, sodass eine Änderung daran
    den Hinweis zurückbringt; der der Dublette nennt die Dokumente, sodass ein weiteres ihn
    zurückbringt.
    """
    documents = [d for d in state.of_kind(Document) if d.owner == user]
    found: list[Finding] = []
    for expected in sorted(state.of_kind(ExpectedDocument), key=lambda e: str(e.address)):
        if expected.owner != user or not expected.due_in(year):
            continue
        matching = matching_documents(documents, expected, year)
        name = expected_name(expected, titles)
        target = f"{expected.address}@{year}"  # je Jahr ein eigener Befund
        if not matching:
            text = f"Erwarteter Beleg für {year} ausstehend: {name}"
            stand = fingerprint("ausstehend", expected.document_kind, expected.description)
            found.append(
                Finding(PENDING, Severity.NOTE, target, text, href=HREF, fingerprint=stand)
            )
        elif len(matching) > 1:
            text = f"Mehrere passende Dokumente für {year}; mögliche Dublette: {name}"
            stand = fingerprint(*(d.id for d in matching))
            found.append(
                Finding(DUPLICATE, Severity.NOTE, target, text, href=HREF, fingerprint=stand)
            )
    return found
