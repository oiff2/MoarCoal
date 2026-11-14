"""Leser der HTML-Dokumente aus Mein ELSTER (Übertragungsprotokoll, eDaten-Belege): exakt, ohne
Claude, reine Funktionen. Der gemeinsame Teil aller Dokumentarten dieses Formats; was ein Feld
bedeutet, entscheidet die Einlese-Regel der Dokumentart.

Aufbau (HTML aus Mein ELSTER):

- Kopf als HTML-Kommentare: `<!-- Belegart: E10 -->`, `<!-- Belegversion: 2025 -->`,
  `<!-- Veranlagungsjahr: -->` (im echten Protokoll oft leer); dazu im Protokoll der Text
  „Eingang auf Server: TT.MM.JJJJ“.
- Jeder Wert ist ein `<span data-name="…">` in einer Tabellenzeile. Der Pfad des Felds ist der
  `data-name` ohne `id-` und ohne den Index `_usb…` einer Wiederholgruppe. Die Zelle vor dem
  Inhalt ist die Bezeichnung, die erste Zelle die Nummer im Vordruck, wenn sie aus 1 bis 3 Ziffern
  besteht. Dieselbe Angabe kann mehrfach vorkommen; jedes Vorkommen bleibt ein eigenes Feld.
"""

import datetime
import re
from dataclasses import dataclass
from html.parser import HTMLParser

HEADER_COMMENT = re.compile(r"^\s*(Belegart|Belegversion|Veranlagungsjahr):\s*(.*?)\s*$")
INDEX_SUFFIX = re.compile(r"_usb([0-9][0-9_\-]*)$")
FORM_LINE = re.compile(r"\d{1,3}")
RECEIVED = re.compile(r"Eingang auf Server:\s*(\d{2})\.(\d{2})\.(\d{4})")
YEAR = re.compile(r"\d{4}")


@dataclass(frozen=True)
class HtmlField:
    """Ein Wert des Dokuments, roh wie gedruckt. `index` ist der Index der Wiederholgruppe."""

    data_name: str
    path: str
    index: str
    form_line: str
    label: str
    text: str


@dataclass(frozen=True)
class ParsedHtml:
    belegart: str
    belegversion: str
    year: int | None  # aus dem Kopf: Veranlagungsjahr, sonst eine vierstellige Belegversion
    received: datetime.date | None
    fields: tuple[HtmlField, ...]


class _Parser(HTMLParser):
    """Liest Kopf und Felder in einem Durchgang."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.header: dict[str, str] = {}
        self.fields: list[HtmlField] = []
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
            path = (data_name[: suffix.start()] if suffix else data_name).removeprefix("id-")
            self.fields.append(
                HtmlField(
                    data_name=data_name,
                    path=path,
                    index=suffix.group(1) if suffix else "",
                    form_line=form_line,
                    label=cells[cell_index - 1] if cell_index >= 2 else "",
                    text=text,
                )
            )


def parse_elster_html(content: bytes) -> ParsedHtml:
    """Kopf und alle Felder mit `data-name`, in der Reihenfolge der Datei."""
    parser = _Parser()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    belegversion = parser.header.get("Belegversion", "")
    year_text = next(
        (t for t in (parser.header.get("Veranlagungsjahr", ""), belegversion) if YEAR.fullmatch(t)),
        None,
    )
    return ParsedHtml(
        belegart=parser.header.get("Belegart", ""),
        belegversion=belegversion,
        year=int(year_text) if year_text else None,
        received=_received("".join(parser.text)),
        fields=tuple(parser.fields),
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
