"""Einlese-Regel des Übertragungsprotokolls: exakt, ohne Claude, reine Funktionen.

Aufbau des Protokolls (HTML aus Mein ELSTER, `Belegart: E10`):

- Kopf als HTML-Kommentare: `<!-- Belegart: E10 -->`, `<!-- Belegversion: 2025 -->`,
  `<!-- Veranlagungsjahr: -->` (im echten Protokoll oft leer); dazu der Text
  „Eingang auf Server: TT.MM.JJJJ“.
- Jedes ausgefüllte Feld ist eine Tabellenzeile; der Inhalt steht in einem `<span data-name="…">`
  in der Zelle ganz rechts. Die E-Kennung ist das letzte Pfadsegment von `data-name` (ohne `id-`
  und ohne den Index `_usb…`), das erste Segment nennt die Anlage. Die Zelle vor dem Inhalt ist die
  Bezeichnung, die erste Zelle die Nummer im Vordruck, wenn sie aus 1 bis 3 Ziffern besteht.
- Felder ohne E-Kennung werden übergangen. Dieselbe E-Kennung kann mehrfach vorkommen
  (Wiederholgruppen); jedes Vorkommen bleibt eine eigene Zeile, nichts wird summiert.
"""

import datetime
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from moarcoal.documents import ReadInError
from moarcoal.modules.tax_year.entries import (
    ELSTER_ID_PATTERN,
    TEXT_MAX,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.storage import Document, Entry

READER_VERSION = 2
MAX_LINES = 5000
BELEGART = "E10"
ELSTER_ID = re.compile(ELSTER_ID_PATTERN)
FORM_LINE = re.compile(r"\d{1,3}")
HEADER_COMMENT = re.compile(r"^\s*(Belegart|Belegversion|Veranlagungsjahr):\s*(.*?)\s*$")
INDEX_SUFFIX = re.compile(r"_usb([0-9][0-9_\-]*)$")
RECEIVED = re.compile(r"Eingang auf Server:\s*(\d{2})\.(\d{2})\.(\d{4})")
YEAR = re.compile(r"\d{4}")


class _Protocol(HTMLParser):
    """Liest Kopf und Felder in einem Durchgang."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.header: dict[str, str] = {}
        self.lines: list[ProtocolLine] = []
        self.text: list[str] = []
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._values: list[tuple[str, str, int]] = []  # data-name, Text, Nummer der Zelle
        self._open: tuple[str, int, list[str]] | None = None  # data-name, Tiefe, Text

    def handle_comment(self, data: str) -> None:
        match = HEADER_COMMENT.match(data)
        if match and match.group(1) not in self.header:
            self.header[match.group(1)] = match.group(2)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells, self._values = [], []
        elif tag in {"td", "th"} and self._cells is not None:
            self._cell = []
        elif tag == "span" and self._cells is not None:
            if self._open is not None:
                name, depth, parts = self._open
                self._open = (name, depth + 1, parts)
            elif name := dict(attrs).get("data-name"):
                self._open = (name, 0, [])

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._open is not None:
            name, depth, parts = self._open
            if depth > 0:
                self._open = (name, depth - 1, parts)
            else:
                self._open = None
                text = " ".join("".join(parts).split())
                self._values.append((name, text, len(self._cells or [])))
        elif tag in {"td", "th"} and self._cell is not None and self._cells is not None:
            self._cells.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            self._finish_row()
            self._cells = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._open is not None:
            self._open[2].append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _finish_row(self) -> None:
        cells = self._cells or []
        form_line = cells[0] if len(cells) >= 2 and FORM_LINE.fullmatch(cells[0]) else ""
        for data_name, text, cell_index in self._values:
            suffix = INDEX_SUFFIX.search(data_name)
            index = suffix.group(1) if suffix else ""
            path = (data_name[: suffix.start()] if suffix else data_name).removeprefix("id-")
            form, _, last = path.rpartition("-")
            if not ELSTER_ID.fullmatch(last) or not form:
                continue
            label = cells[cell_index - 1] if cell_index >= 2 else ""
            self.lines.append(
                ProtocolLine(
                    elster_id=last,
                    form=form.split("-", 1)[0],
                    form_line=form_line,
                    label=label[:TEXT_MAX],
                    content=text[:TEXT_MAX],
                    index=index,
                    data_name=data_name,
                )
            )


@dataclass(frozen=True)
class ParsedProtocol:
    belegart: str
    belegversion: str
    year: int | None  # aus dem Kopf: Veranlagungsjahr, sonst eine vierstellige Belegversion
    received: datetime.date | None
    lines: tuple[ProtocolLine, ...]


def parse_protocol(content: bytes) -> ParsedProtocol:
    """Kopf und alle Felder mit E-Kennung, in der Reihenfolge der Datei."""
    parser = _Protocol()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    belegversion = parser.header.get("Belegversion", "")
    year_text = next(
        (t for t in (parser.header.get("Veranlagungsjahr", ""), belegversion) if YEAR.fullmatch(t)),
        None,
    )
    return ParsedProtocol(
        belegart=parser.header.get("Belegart", ""),
        belegversion=belegversion,
        year=int(year_text) if year_text else None,
        received=_received("".join(parser.text)),
        lines=tuple(parser.lines),
    )


def _received(text: str) -> datetime.date | None:
    match = RECEIVED.search(text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


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
