"""Einlese-Regel des Übertragungsprotokolls: exakt, ohne Claude, reine Funktionen.

Das Protokoll ist ein HTML-Dokument. Eine Tabellenzeile zählt als Zeile des Protokolls, wenn eine
ihrer Zellen genau eine E-Kennung enthält (E und sieben Ziffern); die Zelle davor ist die
Bezeichnung, die Zellen danach sind der übertragene Inhalt.
"""

import re
from html.parser import HTMLParser

from moarcoal.documents import ReadInError
from moarcoal.modules.tax_year.entries import TEXT_MAX, ProtocolLine, ProtocolReading
from moarcoal.storage import Document, Entry

READER_VERSION = 1
MAX_LINES = 5000
EKZ = re.compile(r"E\d{7}")


class _Rows(HTMLParser):
    """Sammelt je Tabellenzeile die Zellentexte und die Zeile der Datei, in der sie beginnt."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[int, list[str]]] = []
        self._row: tuple[int, list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._close_row()
            self._row = (self.getpos()[0], [])
        elif tag in {"td", "th"} and self._row is not None:
            self._close_cell()
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self._close_cell()
        elif tag == "tr":
            self._close_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def close(self) -> None:
        super().close()
        self._close_row()

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row[1].append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None:
            self.rows.append(self._row)
        self._row = None


def parse_protocol(content: bytes) -> tuple[ProtocolLine, ...]:
    """Alle Zeilen mit E-Kennung, in der Reihenfolge der Datei."""
    parser = _Rows()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    lines: list[ProtocolLine] = []
    for source_line, cells in parser.rows:
        index = next((i for i, cell in enumerate(cells) if EKZ.fullmatch(cell)), None)
        if index is None:
            continue
        lines.append(
            ProtocolLine(
                ekz=cells[index],
                label=cells[index - 1][:TEXT_MAX] if index > 0 else "",
                content=" ".join(cell for cell in cells[index + 1 :] if cell)[:TEXT_MAX],
                source_line=source_line,
            )
        )
    return tuple(lines)


def read_in_protocol(document: Document, content: bytes) -> list[Entry]:
    """Einlese-Regel der Dokumentart Übertragungsprotokoll."""
    lines = parse_protocol(content)
    if not lines:
        raise ReadInError(
            "In der Datei steht keine Zeile mit E-Kennung; kein Übertragungsprotokoll?"
        )
    if len(lines) > MAX_LINES:
        raise ReadInError(f"Mehr als {MAX_LINES} Zeilen; kein Übertragungsprotokoll?")
    if document.period_start is None:
        raise ReadInError("Das Dokument hat keinen Bezugszeitraum.")
    reading = ProtocolReading(
        owner=document.owner,
        document=document.address,
        year=document.period_start.year,
        reader_version=READER_VERSION,
        lines=lines,
    )
    return [reading]
