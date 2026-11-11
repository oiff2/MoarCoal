"""Daten des Moduls Steuerjahr: die eingelesenen Zeilen eines Übertragungsprotokolls."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage import Entry, EntryAddress, EntryKind, entry_kind

SCHEMA = "tax_year/1"
TRANSFER_PROTOCOL_KEY = "transfer_protocol"  # Schlüssel der Dokumentart
EKZ_PATTERN = r"^E\d{7}$"
TEXT_MAX = 500


class ProtocolLine(BaseModel):
    """Ein ausgefülltes Feld des Protokolls, roh wie gedruckt; nichts wird umgerechnet.

    `data_name` ist die Fundstelle: der volle Name des Felds im Dokument. `index` ist der Index
    einer Wiederholgruppe (Suffix `_usb…` ohne diese Vorsilbe); dieselbe E-Kennung kann mehrfach
    vorkommen. `form` ist die Anlage (erstes Pfadsegment), `form_line` die Nummer im Vordruck.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ekz: str = Field(pattern=EKZ_PATTERN)
    form: str = Field(min_length=1, max_length=TEXT_MAX)
    form_line: str = Field(pattern=r"^(\d{1,3})?$")
    label: str = Field(max_length=TEXT_MAX)
    content: str = Field(max_length=TEXT_MAX)
    index: str = Field(max_length=TEXT_MAX)
    data_name: str = Field(min_length=1, max_length=TEXT_MAX)


class ProtocolReading(Entry):
    """Ergebnis des Einlesens eines Übertragungsprotokolls, gehört zu genau einem Dokument.

    `reader_version` nennt die Fassung der Einlese-Regel; ändert sie sich, wird neu eingelesen.
    `belegversion` und `received` stammen aus dem Kopf (leer, wenn dort nicht vorhanden).
    """

    document: EntryAddress
    year: int = Field(ge=2000, le=2100)
    reader_version: int = Field(ge=1)
    belegversion: str = Field(default="", max_length=TEXT_MAX)
    received: datetime.date | None = None
    lines: tuple[ProtocolLine, ...]


def reading_path(entry: ProtocolReading) -> str:
    return f"nutzer/{entry.owner}/tax_year/{entry.year}.json"


KINDS: tuple[EntryKind, ...] = (entry_kind(ProtocolReading, SCHEMA, reading_path),)
