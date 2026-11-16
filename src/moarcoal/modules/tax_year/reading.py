"""Einlese-Regel des Übertragungsprotokolls: exakt, ohne Claude, reine Funktionen.

Der Leser des HTML (Kopf, Felder mit `data-name`) ist gemeinsam (`moarcoal.elster_html`). Hier
steht, was das Protokoll (`Belegart: E10`) daraus macht:

- Jedes ausgefüllte Feld mit E-Kennung wird eine Zeile. Die E-Kennung ist das letzte Pfadsegment,
  das erste Segment nennt die Anlage.
- Felder ohne E-Kennung werden übergangen. Dieselbe E-Kennung kann mehrfach vorkommen
  (Wiederholgruppen); jedes Vorkommen bleibt eine eigene Zeile, nichts wird summiert.
"""

import re
from collections.abc import Iterable

from moarcoal.documents import ReadInError
from moarcoal.elster_html import HtmlField, parse_elster_document
from moarcoal.modules.tax_year.entries import (
    ELSTER_ID_PATTERN,
    TEXT_MAX,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.storage import Document, ReadInEntry

READER_VERSION = 2
MAX_LINES = 5000
TITLE = "Übertragungsprotokoll"  # Titel der Dokumentart
BELEGART = "E10"
ELSTER_ID = re.compile(ELSTER_ID_PATTERN)


def protocol_lines(fields: Iterable[HtmlField]) -> tuple[ProtocolLine, ...]:
    """Die Zeilen aller Felder mit E-Kennung, in der Reihenfolge der Datei."""
    return tuple(line for f in fields if (line := _line(f)) is not None)


def _line(field: HtmlField) -> ProtocolLine | None:
    """Die Zeile zu einem Feld des Dokuments; ohne E-Kennung `None`."""
    form, _, last = field.path.rpartition("-")
    if not ELSTER_ID.fullmatch(last) or not form:
        return None
    return ProtocolLine(
        elster_id=last,
        form=form.split("-", 1)[0],
        form_line=field.form_line,
        label=field.label[:TEXT_MAX],
        content=field.text[:TEXT_MAX],
        index=field.index,
        data_name=field.data_name,
    )


def read_in_protocol(document: Document, content: bytes) -> list[ReadInEntry]:
    """Einlese-Regel der Dokumentart Übertragungsprotokoll."""
    year, parsed = parse_elster_document(document, content, BELEGART, TITLE)
    lines = protocol_lines(parsed.fields)
    if not lines:
        raise ReadInError("Im Übertragungsprotokoll steht kein Feld mit E-Kennung.")
    if len(lines) > MAX_LINES:
        raise ReadInError(f"Mehr als {MAX_LINES} Felder; kein Übertragungsprotokoll?")
    reading = ProtocolReading(
        owner=document.owner,
        document=document.address,
        year=year,
        reader_version=READER_VERSION,
        belegversion=parsed.belegversion,
        received=parsed.received,
        lines=lines,
    )
    return [reading]
