"""Baustein Abgebrochene Auslesung: festgehaltener Abbruch des Claude-Aufrufs an einem Dokument."""

import datetime
from typing import Literal

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind

ABORTED_EXTRACTION_SCHEMA = "datenebene/1"


class AbortedExtraction(Entry):
    """Der Claude-Aufruf zu `document` wurde abgebrochen, weil Werkzeuge oder MCP-Server gemeldet
    wurden. Höchstens einer je Dokument; ein weiterer Abbruch ersetzt ihn, eine gelungene
    Auslesung löscht ihn.
    """

    document: EntryAddress
    aborted_at: datetime.datetime
    reason: Literal["tools_reported"] = "tools_reported"


def aborted_extraction_path(entry: AbortedExtraction) -> str:
    return f"users/{entry.owner}/aborted_extractions.json"


ABORTED_EXTRACTION_KIND = entry_kind(
    AbortedExtraction, ABORTED_EXTRACTION_SCHEMA, aborted_extraction_path, falls_with="document"
)
