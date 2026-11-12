"""Baustein Erwarteter Beleg in einfacher Form (docs/grundgeruest.md, 3.2 und 3.6)."""

from typing import Self

from pydantic import Field, model_validator

from moarcoal.storage.entries import Entry, entry_kind

EXPECTED_DOCUMENT_SCHEMA = "datenebene/1"
MIN_YEAR = 2000
MAX_YEAR = 2100
TEXT_MAX = 200


class ExpectedDocument(Entry):
    """Ein Dokument der Dokumentart `document_kind`, das jährlich von `start_year` bis `end_year`
    (einschließlich; leer: ohne Ende) erwartet wird.

    Einfache Form: ohne Aussteller, Zuordnung, Beschaffungsweg und Ausnahmen je Zeitraum.
    """

    document_kind: str = Field(min_length=1)
    start_year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    end_year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    description: str = Field(default="", max_length=TEXT_MAX)

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("Endjahr liegt vor dem Beginnjahr")
        return self

    def due_in(self, year: int) -> bool:
        """Ob für `year` ein Dokument fällig ist."""
        return self.start_year <= year and (self.end_year is None or year <= self.end_year)


def expected_document_path(entry: ExpectedDocument) -> str:
    return f"users/{entry.owner}/expected_documents.json"


EXPECTED_DOCUMENT_KIND = entry_kind(
    ExpectedDocument, EXPECTED_DOCUMENT_SCHEMA, expected_document_path
)
