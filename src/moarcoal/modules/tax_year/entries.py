"""Daten des Moduls Steuerjahr: eingelesene Zeilen eines Übertragungsprotokolls und Eingaben."""

import datetime
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage import Entry, EntryAddress, EntryKind, entry_kind

SCHEMA = "tax_year/1"
TRANSFER_PROTOCOL_KEY = "transfer_protocol"  # Schlüssel der Dokumentart
ELSTER_ID_PATTERN = r"^E\d{7}$"  # einzige Stelle des Musters
TEXT_MAX = 500

type ElsterId = Annotated[str, Field(pattern=ELSTER_ID_PATTERN)]


class ProtocolLine(BaseModel):
    """Ein ausgefülltes Feld des Protokolls, roh wie gedruckt; nichts wird umgerechnet.

    `data_name` ist die Fundstelle: der volle Name des Felds im Dokument. `index` ist der Index
    einer Wiederholgruppe (Suffix `_usb…` ohne diese Vorsilbe); dieselbe E-Kennung kann mehrfach
    vorkommen. `form` ist die Anlage (erstes Pfadsegment), `form_line` die Nummer im Vordruck.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    elster_id: ElsterId
    form: str = Field(min_length=1, max_length=TEXT_MAX)
    form_line: str = Field(pattern=r"^(\d{1,3})?$")
    label: str = Field(max_length=TEXT_MAX)
    content: str = Field(max_length=TEXT_MAX)
    index: str = Field(max_length=TEXT_MAX)
    data_name: str = Field(min_length=1, max_length=TEXT_MAX)


class ProtocolReading(Entry):
    """Ergebnis des Einlesens eines Übertragungsprotokolls, gehört zu genau einem Dokument.

    `reader_version` nennt die Fassung der Einlese-Regel. Die Einlesung fällt mit dem Dokument weg;
    nach dem Löschen lässt sich die Datei neu aufnehmen und wird neu eingelesen.
    `belegversion` und `received` stammen aus dem Kopf (leer, wenn dort nicht vorhanden).
    """

    document: EntryAddress
    year: int = Field(ge=2000, le=2100)
    reader_version: int = Field(ge=1)
    belegversion: str = Field(default="", max_length=TEXT_MAX)
    received: datetime.date | None = None
    lines: tuple[ProtocolLine, ...]


class FormInput(Entry):
    """Eingabe zu einem Eintippfeld der Anlage, direkt im Steuerjahr erfasst (Nutzereingabe).

    `content` steht so, wie sie in das Feld in ELSTER einzutragen ist (Anzahl Tage als Zahl, eine
    Auswahl als ihr Text); die Prüfung gegen das Feld macht der Vorgang in `inputs`. Je Nutzer,
    Jahr und Feld höchstens eine.
    """

    year: int = Field(ge=2000, le=2100)
    elster_id: ElsterId
    content: str = Field(min_length=1, max_length=TEXT_MAX)


def check_input(entry: FormInput, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Schreibweg: nur eine Eingabe je Nutzer, Jahr und Feld."""
    same = [
        e
        for e in entries.values()
        if isinstance(e, FormInput)
        and (e.owner, e.year, e.elster_id) == (entry.owner, entry.year, entry.elster_id)
    ]
    if len(same) > 1:
        return f"Für {entry.year} gibt es zu {entry.elster_id} schon eine Eingabe"
    return None


def yearly_path(entry: ProtocolReading | FormInput) -> str:
    return f"users/{entry.owner}/tax_year/{entry.year}.json"


KINDS: tuple[EntryKind, ...] = (
    entry_kind(ProtocolReading, SCHEMA, yearly_path, falls_with="document"),
    entry_kind(FormInput, SCHEMA, yearly_path, check=check_input),
)
