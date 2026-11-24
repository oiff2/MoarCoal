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
from collections.abc import Collection
from dataclasses import dataclass
from html.parser import HTMLParser

from moarcoal.documents import ReadInError
from moarcoal.storage import Document
from moarcoal.values.model import parse_cents

HEADER_COMMENT = re.compile(r"^\s*(Belegart|Belegversion|Veranlagungsjahr):\s*(.*?)\s*$")
INDEX_SUFFIX = re.compile(r"_usb([0-9][0-9_\-]*)$")
FORM_LINE = re.compile(r"\d{1,3}")
RECEIVED = re.compile(r"Eingang auf Server:\s*(\d{2})\.(\d{2})\.(\d{4})")
YEAR = re.compile(r"\d{4}")
PDF_START = b"%PDF-"


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


def parse_elster_html(content: bytes, title: str) -> ParsedHtml:
    """Kopf und alle Felder mit `data-name`, in der Reihenfolge der Datei. `title` ist der Titel
    der Dokumentart und steht in der Meldung, wenn die Datei kein HTML aus Mein ELSTER ist: ein
    PDF oder eine Datei ohne Kopfkommentar `Belegart` und ohne Feld mit `data-name`."""
    is_pdf = content.lstrip().startswith(PDF_START)
    parser = _Parser()
    if not is_pdf:
        parser.feed(content.decode("utf-8", errors="replace"))
        parser.close()
    if is_pdf or ("Belegart" not in parser.header and not parser.fields):
        hint = "sieht nach einem PDF aus" if is_pdf else "keine HTML-Datei aus Mein ELSTER"
        raise ReadInError(
            f"Unerwartetes Format ({hint}). "
            f"Für die Dokumentart {title} wird die HTML-Datei aus Mein ELSTER gebraucht."
        )
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


def parse_elster_document(
    document: Document, content: bytes, belegart: str, title: str
) -> tuple[int, ParsedHtml]:
    """Liest die Datei eines Dokuments mit Bezugszeitraum und prüft den Kopf: die Belegart der
    Dokumentart (Titel `title`) und, falls der Kopf eines nennt, das Jahr des Dokuments. Gibt das
    Jahr des Dokuments und die gelesene Datei zurück; sonst `ReadInError`."""
    if document.period_start is None:
        raise ReadInError("Das Dokument hat keinen Bezugszeitraum.")
    parsed = parse_elster_html(content, title)
    if parsed.belegart != belegart:
        raise ReadInError(
            f"Die Datei passt nicht zur Dokumentart {title} (Belegart {belegart} fehlt im Kopf)."
        )
    year = document.period_start.year
    if parsed.year is not None and parsed.year != year:
        raise ReadInError(
            f"Die Datei ({title}) gehört zum Steuerjahr {parsed.year}, eingetragen ist {year}."
        )
    return year, parsed


def _received(text: str) -> datetime.date | None:
    match = RECEIVED.search(text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def single_field(fields: list[HtmlField], belegart: str, path: str, name: str) -> HtmlField | None:
    """Das eine Feld mit dem Pfad `path` (ohne `<belegart>-`); fehlt es: `None`. Kommt es mehrfach
    vor (Wiederholgruppe), ist nicht entschieden, welcher Wert gilt: `ReadInError` statt Raten."""
    found = [f for f in fields if f.path == f"{belegart}-{path}"]
    if len(found) > 1:
        raise ReadInError(
            f"{name} steht {len(found)}-mal in der Datei; welcher Wert gilt, ist offen."
        )
    return found[0] if found else None


def unrecognized_paths(fields: list[HtmlField], belegart: str, known: Collection[str]) -> list[str]:
    """Die Pfade der Datei (ohne `<belegart>-`), die die Einlese-Regel nicht kennt, sortiert und
    ohne Dopplung."""
    prefix = f"{belegart}-"
    return sorted({f.path.removeprefix(prefix) for f in fields} - set(known))


def read_cents(field: HtmlField, name: str) -> int:
    """Der Betrag des Felds in ganzen Cent, nie negativ; sonst `ReadInError` mit `name`."""
    cents = parse_cents(field.text)
    if cents is None or cents < 0:
        raise ReadInError(f"{name}: „{field.text}“ ist kein Betrag in Euro und Cent.")
    return cents
