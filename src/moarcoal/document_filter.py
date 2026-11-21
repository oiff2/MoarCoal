"""Zustand der Dokumente (Belege-Seite, bei jeder Anfrage abgeleitet, nie gespeichert) sowie
Suche und Dateityp-Filter der Seite."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from moarcoal.documents import DocumentKind
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import Document, State


class DocumentState(StrEnum):
    """Der abgeleitete Zustand eines Dokuments; ohne Art `BELEG`."""

    TO_CONFIRM = "zu bestätigen"
    TO_EXTRACT = "auszulesen"
    DONE = "fertig"
    BELEG = "Beleg"


def document_state(
    state: State, kinds: Mapping[str, DocumentKind], document: Document
) -> DocumentState:
    """„zu bestätigen“ (der neueste Vorschlag hat offene Felder), „auszulesen“ (die Art hat eine
    Auslese-Vorlage, aber es gibt keinen Vorschlag), „fertig“ oder, ohne Art, „Beleg“ (neutral)."""
    if not document.document_kind:
        return DocumentState.BELEG
    proposal = latest_proposal(state, document)
    if proposal is not None:
        return DocumentState.TO_CONFIRM if proposal.open_keys else DocumentState.DONE
    if template_of(kinds, document) is not None:
        return DocumentState.TO_EXTRACT
    return DocumentState.DONE


class FileType(StrEnum):
    """Der Dateityp einer Datei, an der Endung erkannt: Suche und Filter der Belege-Seite."""

    PDF = "pdf"
    EDATEN = "edaten"
    IMAGE = "bild"
    TABLE = "tabelle"
    OTHER = "sonstiges"

    @property
    def label(self) -> str:
        return {
            FileType.PDF: "PDF",
            FileType.EDATEN: "eDaten",
            FileType.IMAGE: "Bild",
            FileType.TABLE: "Tabelle",
            FileType.OTHER: "Sonstiges",
        }[self]


_EXTENSIONS: dict[FileType, tuple[str, ...]] = {
    FileType.PDF: (".pdf",),
    FileType.EDATEN: (".html", ".htm", ".xml"),
    FileType.IMAGE: (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".tif", ".tiff", ".bmp"),
    FileType.TABLE: (".xlsx", ".xls", ".ods", ".csv"),
}


def file_type(path: str) -> FileType:
    """Der Dateityp nach der Endung (ohne Groß-/Kleinschreibung); jede andere Endung ist
    „Sonstiges“. Die einzige Zuordnung Endung zu Dateityp."""
    suffix = PurePosixPath(path).suffix.lower()
    return next((t for t, endings in _EXTENSIONS.items() if suffix in endings), FileType.OTHER)


def parse_file_types(values: Iterable[str]) -> frozenset[FileType]:
    """Die Dateitypen aus den Werten der Adresse; Unbekanntes zählt nicht."""
    known = {t.value: t for t in FileType}
    return frozenset(known[v] for v in values if v in known)


@dataclass(frozen=True)
class SearchFilter:
    """Suche und Dateityp-Filter der Belege-Seite. Ein leerer Suchtext und keine gewählten
    Dateitypen lassen alles durch; mehrere Dateitypen gelten als „oder“."""

    query: str = ""
    types: frozenset[FileType] = frozenset()

    @property
    def active(self) -> bool:
        return bool(self.query.strip() or self.types)

    def without_types(self) -> "SearchFilter":
        return SearchFilter(self.query, frozenset())

    def matches(self, texts: Iterable[str], types: Iterable[FileType]) -> bool:
        """Enthält ein Text den Suchtext (ohne Groß-/Kleinschreibung) und ist einer der Typen
        gewählt? Wer keine Datei hat (`types` leer), fällt bei gewähltem Dateityp heraus."""
        needle = self.query.strip().casefold()
        if needle and not any(needle in text.casefold() for text in texts):
            return False
        return not self.types or any(t in self.types for t in types)
