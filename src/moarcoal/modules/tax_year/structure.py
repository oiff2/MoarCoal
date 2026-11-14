"""Struktur einer Anlage je Steuerjahr: was Mein ELSTER zeigt, ohne Bedeutung.

Die Dateien in `strukturen/` erzeugt `tools/elster_page_fields.py` aus gespeicherten Seiten von
Mein ELSTER (nie Werte, nie Namen). Die Bedeutung eines Felds (Wert, Richtung, Runden, EStB) steht
im Katalog (`anlage_n.py`) und verweist per E-Kennung auf die Struktur.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from moarcoal.modules.tax_year.entries import ElsterId

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
        StructureField(f["e_kennung"], f["page"], tuple(f["headings"]), f["line"], f["label"])
        for f in data["fields"]
    )
    ids = [f.e_kennung for f in fields]
    if len(ids) != len(set(ids)):
        raise ValueError("Struktur mit doppelter E-Kennung")
    return FormStructure(data["form"], data["year"], bool(data["provisional"]), fields)


def load_structure(form: str, year: int, directory: Path = DIRECTORY) -> FormStructure:
    return parse_structure((directory / f"{form.lower()}-{year}.json").read_text(encoding="utf-8"))
