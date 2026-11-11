"""Daten des Moduls Steuerjahr: die eingelesenen Zeilen eines Übertragungsprotokolls."""

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage import Entry, EntryAddress, EntryKind, entry_kind

SCHEMA = "tax_year/1"
TRANSFER_PROTOCOL_KEY = "transfer_protocol"  # Schlüssel der Dokumentart
EKZ_PATTERN = r"^E\d{7}$"
TEXT_MAX = 500


class ProtocolLine(BaseModel):
    """Eine Zeile des Protokolls: E-Kennung, Bezeichnung und Inhalt, wie übertragen.

    `source_line` ist die Fundstelle: die Zeile in der HTML-Datei, in der die Tabellenzeile beginnt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ekz: str = Field(pattern=EKZ_PATTERN)
    label: str = Field(max_length=TEXT_MAX)
    content: str = Field(max_length=TEXT_MAX)
    source_line: int = Field(ge=1)


class ProtocolReading(Entry):
    """Ergebnis des Einlesens eines Übertragungsprotokolls, gehört zu genau einem Dokument.

    `reader_version` nennt die Fassung der Einlese-Regel; ändert sie sich, wird neu eingelesen.
    """

    document: EntryAddress
    year: int = Field(ge=2000, le=2100)
    reader_version: int = Field(ge=1)
    lines: tuple[ProtocolLine, ...]


def reading_path(entry: ProtocolReading) -> str:
    return f"nutzer/{entry.owner}/tax_year/{entry.year}.json"


KINDS: tuple[EntryKind, ...] = (entry_kind(ProtocolReading, SCHEMA, reading_path),)
