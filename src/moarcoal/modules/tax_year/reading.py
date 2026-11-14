"""Einlese-Regel des Übertragungsprotokolls: exakt, ohne Claude, reine Funktionen.

Der Leser des HTML (Kopf, Felder mit `data-name`) ist gemeinsam (`moarcoal.elster_html`). Hier
steht, was das Protokoll (`Belegart: E10`) daraus macht:

- Jedes ausgefüllte Feld mit E-Kennung wird eine Zeile. Die E-Kennung ist das letzte Pfadsegment,
  das erste Segment nennt die Anlage.
- Felder ohne E-Kennung werden übergangen. Dieselbe E-Kennung kann mehrfach vorkommen
  (Wiederholgruppen); jedes Vorkommen bleibt eine eigene Zeile, nichts wird summiert.
"""

import datetime
import re
from dataclasses import dataclass

from moarcoal.documents import ReadInError
from moarcoal.elster_html import HtmlField, parse_elster_html
from moarcoal.modules.tax_year.entries import (
    ELSTER_ID_PATTERN,
    TEXT_MAX,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.storage import Document, Entry

READER_VERSION = 2
MAX_LINES = 5000
TITLE = "Übertragungsprotokoll"  # Titel der Dokumentart
BELEGART = "E10"
ELSTER_ID = re.compile(ELSTER_ID_PATTERN)


@dataclass(frozen=True)
class ParsedProtocol:
    belegart: str
    belegversion: str
    year: int | None  # aus dem Kopf: Veranlagungsjahr, sonst eine vierstellige Belegversion
    received: datetime.date | None
    lines: tuple[ProtocolLine, ...]


def parse_protocol(content: bytes) -> ParsedProtocol:
    """Kopf und alle Felder mit E-Kennung, in der Reihenfolge der Datei."""
    parsed = parse_elster_html(content, TITLE)
    return ParsedProtocol(
        belegart=parsed.belegart,
        belegversion=parsed.belegversion,
        year=parsed.year,
        received=parsed.received,
        lines=tuple(line for f in parsed.fields if (line := _line(f)) is not None),
    )


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


def read_in_protocol(document: Document, content: bytes) -> list[Entry]:
    """Einlese-Regel der Dokumentart Übertragungsprotokoll."""
    if document.period_start is None:
        raise ReadInError("Das Dokument hat keinen Bezugszeitraum.")
    parsed = parse_protocol(content)
    if parsed.belegart != BELEGART:
        raise ReadInError("Die Datei ist kein Übertragungsprotokoll (Belegart E10 fehlt im Kopf).")
    year = document.period_start.year
    if parsed.year is not None and parsed.year != year:
        raise ReadInError(
            f"Das Übertragungsprotokoll gehört zum Steuerjahr {parsed.year}, "
            f"eingetragen ist {year}."
        )
    if not parsed.lines:
        raise ReadInError("Im Übertragungsprotokoll steht kein Feld mit E-Kennung.")
    if len(parsed.lines) > MAX_LINES:
        raise ReadInError(f"Mehr als {MAX_LINES} Felder; kein Übertragungsprotokoll?")
    reading = ProtocolReading(
        owner=document.owner,
        document=document.address,
        year=year,
        reader_version=READER_VERSION,
        belegversion=parsed.belegversion,
        received=parsed.received,
        lines=parsed.lines,
    )
    return [reading]
