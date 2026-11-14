"""Baustein Dokument: Verweis auf eine Datei an einem Ablageort (docs/grundgeruest.md, 3.2)."""

import datetime
from collections.abc import Collection, Mapping
from typing import Self

from pydantic import Field, model_validator

from moarcoal.storage.entries import Entry, EntryAddress, EntryKind, entry_kind

DOCUMENT_SCHEMA = "datenebene/1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: der Reiter Dokumente, das Dokument gewählt."""
    return f"/belege/dokumente?dokument={document_id}"


class Document(Entry):
    """Eine aufgenommene Datei: Ablageort + relativer Pfad + SHA-256, höchstens eine Dokumentart.

    Die Datei bleibt am Ablageort und wird nur gelesen (ADR 0003). Hat die Dokumentart einen
    Bezugszeitraum, stehen Beginn und Ende hier. `taken_in_at` ist der Zeitpunkt des Aufnehmens
    (UTC; bei älteren Dokumenten leer). `issuer` verweist freiwillig auf einen Aussteller.
    """

    site: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    document_kind: str | None = None
    issuer: EntryAddress | None = None
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    taken_in_at: datetime.datetime | None = None

    @model_validator(mode="after")
    def _issuer_is_an_issuer(self) -> Self:
        if self.issuer is not None and self.issuer.kind != "Issuer":
            raise ValueError("Aussteller verweist nicht auf einen Aussteller")
        return self

    @model_validator(mode="after")
    def _period_is_complete(self) -> Self:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Bezugszeitraum braucht Beginn und Ende")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("Bezugszeitraum endet vor seinem Beginn")
        return self

    @property
    def url(self) -> str:
        return document_url(self.id)

    def touches_year(self, year: int) -> bool:
        """Ob der Bezugszeitraum das Jahr berührt; ohne Bezugszeitraum nie."""
        return (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start.year <= year <= self.period_end.year
        )


def document_path(entry: Document) -> str:
    return f"users/{entry.owner}/documents.json"


def period_clash(
    entries: Mapping[EntryAddress, Entry], document: Document, once_per_period: Collection[str]
) -> Document | None:
    """Das andere Dokument desselben Nutzers mit derselben Art und demselben Bezugszeitraum, wenn
    die Art (Schlüssel in `once_per_period`) je Bezugszeitraum nur eines erlaubt."""
    if document.document_kind not in once_per_period or document.period_start is None:
        return None
    return next(
        (
            e
            for e in entries.values()
            if isinstance(e, Document)
            and e.address != document.address
            and (e.owner, e.document_kind, e.period_start)
            == (document.owner, document.document_kind, document.period_start)
        ),
        None,
    )


def exists_already(title: str, document: Document) -> str:
    year = document.period_start.year if document.period_start else ""
    return f"Existiert bereits: {title} {year}"


def document_entry_kind(once_per_period: Mapping[str, str] | None = None) -> EntryKind:
    """Die Eintragsart Dokument. `once_per_period` (Schlüssel -> Name der Dokumentarten, die je
    Bezugszeitraum und Nutzer nur ein Dokument erlauben) kommt aus den Modulanmeldungen; die
    Prüfung läuft im Schreibweg gegen den Stand nach dem Vorgang."""
    once = once_per_period or {}

    def check(document: Document, entries: Mapping[EntryAddress, Entry]) -> str | None:
        """Aussteller existiert; je Bezugszeitraum nur ein Dokument, wo verlangt."""
        if document.issuer is not None and document.issuer not in entries:
            return "Aussteller existiert nicht."
        other = period_clash(entries, document, once)
        if other is not None and document.document_kind is not None:
            return exists_already(once[document.document_kind], other)
        return None

    return entry_kind(Document, DOCUMENT_SCHEMA, document_path, check=check)
