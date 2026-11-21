"""Daten des Moduls Steuerjahr: eingelesene Zeilen eines Übertragungsprotokolls und Eingaben."""

import datetime
import re
from collections.abc import Callable, Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.storage import Entry, EntryAddress, EntryKind, ReadInEntry, entry_kind

MODULE_KEY = "tax_year"
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


class ProtocolReading(ReadInEntry):
    """Ergebnis des Einlesens eines Übertragungsprotokolls, gehört zu genau einem Dokument.

    Dokument und Fassung der Einlese-Regel trägt `ReadInEntry`; ändert sich die Fassung, liest
    die Datenebene beim Start neu ein. Die Einlesung fällt mit dem Dokument weg; nach dem Löschen
    lässt sich die Datei neu aufnehmen und wird neu eingelesen. `belegversion` und `received`
    stammen aus dem Kopf (leer, wenn dort nicht vorhanden).
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    belegversion: str = Field(default="", max_length=TEXT_MAX)
    received: datetime.date | None = None
    lines: tuple[ProtocolLine, ...]


class FormInput(Entry):
    """Eingabe zu einem Eintippfeld der Anlage, direkt im Steuerjahr erfasst (Nutzereingabe).

    `content` steht so, wie sie in das Feld in ELSTER einzutragen ist (die Auswahl als ihr Text).
    Der Schreibweg prüft sie gegen das Feld (`kinds`), auch beim Laden: eine Eingabe zu einem Feld,
    das keine mehr nimmt, hält den Start an. Je Nutzer, Jahr und Feld höchstens eine.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    elster_id: ElsterId
    content: str = Field(min_length=1, max_length=TEXT_MAX)


PHONE_PATTERN = re.compile(r"[0-9+()/\- ]+")


class YearPersonInput(Entry):
    """Eingabe zur Person im Steuerjahr: ausgeübter Beruf, Telefon für Rückfragen und die Auswahl
    „In dieser Steuererklärung“ (als ihr Text). Je Nutzer und Jahr höchstens eine (Schreibweg);
    `None` heißt noch nicht angegeben. Die Felder von ESt 1 A übernehmen sie später (#167).
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    occupation: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    phone: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    in_this_return: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)


def taken_order(moment: datetime.datetime | None, entry_id: str) -> tuple[bool, float, str]:
    """Reihenfolge nach Aufnahmezeitpunkt (ohne Zeitpunkt zuerst), bei Gleichstand nach `id`."""
    return (moment is not None, moment.timestamp() if moment else 0.0, entry_id)


type FieldCheck = Callable[[FormInput], str | None]
"""Warum eine Eingabe nicht zu ihrem Feld passt; `None`, wenn sie passt."""


def check_input(
    entry: FormInput, entries: Mapping[EntryAddress, Entry], fits_field: FieldCheck
) -> str | None:
    """Schreibweg: die Eingabe passt zu ihrem Feld, nur eine je Nutzer, Jahr und Feld."""
    if (reason := fits_field(entry)) is not None:
        return reason
    same = [
        e
        for e in entries.values()
        if isinstance(e, FormInput)
        and (e.owner, e.year, e.elster_id) == (entry.owner, entry.year, entry.elster_id)
    ]
    if len(same) > 1:
        return f"Für {entry.year} gibt es zu {entry.elster_id} schon eine Eingabe"
    return None


def check_person_input(entry: YearPersonInput, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Schreibweg: das Telefon ist eine Nummer, nur eine Eingabe zur Person je Nutzer und Jahr."""
    if entry.phone is not None and not PHONE_PATTERN.fullmatch(entry.phone):
        return "Telefon: nur Ziffern, + ( ) / - und Leerzeichen"
    same = [
        e
        for e in entries.values()
        if isinstance(e, YearPersonInput) and (e.owner, e.year) == (entry.owner, entry.year)
    ]
    if len(same) > 1:
        return f"Für {entry.year} gibt es schon Eingaben zur Person"
    return None


def yearly_path(entry: ProtocolReading | FormInput | YearPersonInput) -> str:
    return f"users/{entry.owner}/tax_year/{entry.year}.json"


def kinds(fits_field: FieldCheck) -> tuple[EntryKind, ...]:
    """Die Eintragsarten des Moduls; `fits_field` prüft eine Eingabe gegen den Feldkatalog."""

    def check(entry: FormInput, entries: Mapping[EntryAddress, Entry]) -> str | None:
        return check_input(entry, entries, fits_field)

    return (
        entry_kind(ProtocolReading, SCHEMA, yearly_path, falls_with="document", label="Einlesung"),
        entry_kind(FormInput, SCHEMA, yearly_path, check=check, check_on_load=True),
        entry_kind(YearPersonInput, SCHEMA, yearly_path, check=check_person_input),
    )
