"""Struktur einer Anlage je Steuerjahr: was Mein ELSTER zeigt, ohne Bedeutung.

Die Dateien in `strukturen/` erzeugt `tools/elster_page_fields.py` aus gespeicherten Seiten von
Mein ELSTER (nie Werte, nie Namen). Die Bedeutung eines Felds (Wert, Richtung, Runden, EStB) steht
im Katalog (`anlage_n.py`) und verweist per E-Kennung auf die Struktur.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from moarcoal.modules.tax_year.entries import ElsterId
from moarcoal.modules.tax_year.fields import FormField

SCHEMA = 1  # wie im Werkzeug
DIRECTORY = Path(__file__).parent / "strukturen"


class UnknownElsterId(KeyError):
    """Eine E-Kennung, auf die der Katalog verweist, fehlt in der Struktur des Jahrs."""


@dataclass(frozen=True)
class StructureField:
    """Ein Feld, wie Mein ELSTER es zeigt: Seite, Überschriften darunter, Nr. im Vordruck."""

    e_kennung: ElsterId
    page: str
    headings: tuple[str, ...]
    line: str
    label: str
    options: tuple[str, ...] = ()  # feste Auswahl; leer: keine
    free_text: bool = False  # Vorschlagsliste: nimmt auch einen eigenen Text


@dataclass(frozen=True)
class FormStructure:
    """Die Felder einer Anlage in einem Steuerjahr in Seitenreihenfolge von Mein ELSTER.

    `provisional`: nicht aus den Seiten erzeugt, sondern vorläufig aus dem Katalog abgeleitet.
    """

    form: str
    year: int
    provisional: bool
    fields: tuple[StructureField, ...]

    def get(self, e_kennung: str) -> StructureField:
        for field in self.fields:
            if field.e_kennung == e_kennung:
                return field
        raise UnknownElsterId(
            f"{e_kennung} fehlt in der Struktur der Anlage {self.form} {self.year}"
        )


def parse_structure(text: str) -> FormStructure:
    data = json.loads(text)
    if data.get("schema") != SCHEMA:
        raise ValueError(f"Struktur mit Schema {data.get('schema')}, erwartet {SCHEMA}")
    fields = tuple(
        StructureField(
            f["e_kennung"],
            f["page"],
            tuple(f["headings"]),
            f["line"],
            f["label"],
            tuple(f.get("options", ())),
            bool(f.get("free_text", False)),
        )
        for f in data["fields"]
    )
    ids = [f.e_kennung for f in fields]
    if len(ids) != len(set(ids)):
        raise ValueError("Struktur mit doppelter E-Kennung")
    return FormStructure(data["form"], data["year"], bool(data["provisional"]), fields)


def load_structure(form: str, year: int, directory: Path = DIRECTORY) -> FormStructure:
    return parse_structure((directory / f"{form.lower()}-{year}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PageRow:
    """Ein Katalogfeld auf seiner Seite; `headings`: die hier neu beginnenden Überschriften."""

    field: FormField
    structure: StructureField
    headings: tuple[str, ...]


@dataclass(frozen=True)
class FormPage:
    """Eine Seite der Anlage wie in Mein ELSTER, mit den Katalogfeldern darauf."""

    slug: str
    title: str
    rows: tuple[PageRow, ...]


def _first_line(rows: Sequence[PageRow]) -> int:
    """Kleinste Nr. im Vordruck der Seite: die Vordrucknummern laufen in Seitenreihenfolge."""
    numbers = [int(r.structure.line) for r in rows if r.structure.line.isdigit()]
    return min(numbers, default=10**6)


def _slug(title: str) -> str:
    number, separator, _ = title.partition(" - ")
    if separator and number.isdigit():
        return number
    return "-".join(re.findall(r"[a-zäöüß0-9]+", title.lower())[:3])


def form_pages(structure: FormStructure, fields: Iterable[FormField]) -> tuple[FormPage, ...]:
    """Die Seiten der Anlage in Mein-ELSTER-Reihenfolge, je mit den Feldern aus `fields`.

    Seiten ohne Katalogfeld entfallen, Felder der Struktur ohne Katalogeintrag auch. Die Reihenfolge
    der Seiten folgt der Nr. im Vordruck (die Dateien der Struktur liegen nach Dateinamen, nicht
    nach Seiten), die der Felder der Struktur.
    """
    wanted = {f.elster_id: f for f in fields if f.elster_id}
    by_page: dict[str, list[PageRow]] = {}
    previous: tuple[str, ...] = ()
    previous_page = ""
    for described in structure.fields:
        field = wanted.get(described.e_kennung)
        if field is None:
            continue
        if described.page != previous_page:
            previous = ()
            previous_page = described.page
        shown = () if described.headings == previous else described.headings
        previous = described.headings
        by_page.setdefault(described.page, []).append(PageRow(field, described, shown))
    ordered = sorted(by_page.items(), key=lambda item: _first_line(item[1]))
    return tuple(FormPage(_slug(title), title, tuple(rows)) for title, rows in ordered)
