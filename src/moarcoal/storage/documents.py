"""Baustein Dokument: Verweis auf eine Datei an einem Ablageort (docs/grundgeruest.md, 3.2)."""

import datetime
from typing import Self

from pydantic import Field, model_validator

from moarcoal.storage.entries import Entry, EntryKind, entry_kind

DOCUMENT_SCHEMA = "datenebene/1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class Document(Entry):
    """Eine aufgenommene Datei: Ablageort + relativer Pfad + SHA-256, höchstens eine Dokumentart.

    Die Datei bleibt am Ablageort und wird nur gelesen (ADR 0003). Hat die Dokumentart einen
    Bezugszeitraum, stehen Beginn und Ende hier. `taken_in_at` ist der Zeitpunkt des Aufnehmens
    (UTC; bei älteren Dokumenten leer).
    """

    site: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    document_kind: str | None = None
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    taken_in_at: datetime.datetime | None = None

    @model_validator(mode="after")
    def _period_is_complete(self) -> Self:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Bezugszeitraum braucht Beginn und Ende")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("Bezugszeitraum endet vor seinem Beginn")
        return self


def document_path(entry: Document) -> str:
    return f"users/{entry.owner}/documents.json"


DATA_LAYER_KINDS: tuple[EntryKind, ...] = (entry_kind(Document, DOCUMENT_SCHEMA, document_path),)
