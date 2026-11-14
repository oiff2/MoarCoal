"""Auslese-Vorlage: was ein Modul für eine Dokumentart auslesen lassen will (Spec 3.6, Abschnitt 7).

Die Vorlage nennt die Felder mit Schlüssel, Bezeichnung, Einheit und Hinweis für Claude und eine
Fassungsnummer. Daraus entstehen das JSON-Schema und der Hinweis für den `Extractor`.
"""

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from moarcoal.storage import Content
from moarcoal.values.model import parse_german_number

type Confirmed = Content | Decimal
"""Inhalt eines bestätigten Felds, wie ihn ein Modul bekommt: Felder mit Einheit als `Decimal`."""


@dataclass(frozen=True)
class TemplateField:
    """Ein Feld der Vorlage: `key` ist der Feldschlüssel, `hint` der Hinweis für Claude."""

    key: str
    label: str
    unit: str = ""
    hint: str = ""

    @property
    def description(self) -> str:
        parts = [self.label]
        if self.unit:
            parts.append(f"Einheit: {self.unit}")
        if self.hint:
            parts.append(self.hint)
        return ". ".join(parts)

    def read(self, content: Content) -> Confirmed:
        """Inhalt in der Form, die das Modul bekommt; gleich, ob ausgelesen oder korrigiert.

        Ein Feld mit Einheit ist eine Zahl: aus Claudes Zahl oder einem deutschen Zahltext wird
        `Decimal`, leer bleibt `None`. Alles andere bleibt, wie es ist. Ist der Inhalt eines Felds
        mit Einheit keine Zahl, folgt `ValueError`.
        """
        if not self.unit or content is None:
            return content
        if isinstance(content, bool):
            raise ValueError(f"{self.label}: Zahl erwartet")
        if isinstance(content, int | float):
            return Decimal(str(content))
        if not content.strip():
            return None
        number = parse_german_number(content)
        if number is None:
            raise ValueError(f"{self.label}: Zahl erwartet, z. B. 1.234,56")
        return number


MAX_ROWS = 500
"""Obergrenze der Zeilen einer Liste in der Antwort (im Schema festgehalten)."""


def row_key(rows_key: str, number: int, column: str) -> str:
    """Feldschlüssel einer Zelle der Liste im Vorschlag: `<Liste>.<Zeile ab 1>.<Spalte>`."""
    return f"{rows_key}.{number}.{column}"


def split_row_key(key: str) -> tuple[str, int, str] | None:
    """Gegenstück zu `row_key`; `None`, wenn `key` keine Zelle einer Liste nennt."""
    parts = key.split(".")
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), parts[2]


@dataclass(frozen=True)
class ExtractionTemplate:
    """Felder einer Dokumentart, die Claude lesen soll, mit Fassungsnummer (`version`).

    Eine Vorlage kann zusätzlich eine Liste gleichartiger Zeilen auslesen lassen (z. B. die Reisen
    einer Aufstellung): `rows_key` nennt sie, `row_fields` ihre Spalten, `row_label` eine Zeile in
    der Oberfläche (z. B. „Reise“). Im Vorschlag wird jede Zelle ein eigenes Feld mit dem Schlüssel
    `row_key(rows_key, Zeile, Spalte)`; Bestätigen und Lesen bestätigter Felder bleiben damit je
    Feld wie überall.
    """

    version: int
    fields: tuple[TemplateField, ...]
    rows_key: str = ""
    row_fields: tuple[TemplateField, ...] = ()
    row_label: str = "Zeile"

    def __post_init__(self) -> None:
        keys = [field.key for field in self.fields]
        columns = [field.key for field in self.row_fields]
        if not keys or len(set(keys)) != len(keys) or not all(keys):
            raise ValueError("Feldschlüssel der Vorlage müssen vorhanden und eindeutig sein")
        if bool(self.rows_key) != bool(self.row_fields):
            raise ValueError("Eine Liste braucht Schlüssel und Spalten")
        if self.rows_key and (self.rows_key in keys or "." in self.rows_key):
            raise ValueError("Schlüssel der Liste muss eindeutig sein und darf keinen Punkt haben")
        if len(set(columns)) != len(columns) or not all(c and "." not in c for c in columns):
            raise ValueError("Spaltenschlüssel müssen eindeutig sein und dürfen keinen Punkt haben")
        if any("." in key for key in keys):
            raise ValueError("Feldschlüssel dürfen keinen Punkt enthalten")

    def field(self, key: str) -> TemplateField | None:
        """Das Feld zum Schlüssel; für eine Zelle der Liste die Spalte mit Zeilennummer im Namen."""
        found = next((f for f in self.fields if f.key == key), None)
        if found is not None or not (cell := split_row_key(key)):
            return found
        name, number, column = cell
        spec = next((f for f in self.row_fields if f.key == column), None)
        if name != self.rows_key or spec is None:
            return None
        return dataclasses.replace(spec, label=f"{spec.label} ({self.row_label} {number})")

    def expected_keys(self, given: Iterable[str]) -> list[str]:
        """Schlüssel eines Vorschlags: die Felder, dann alle Spalten jeder Zeile aus `given`."""
        numbers = sorted(
            {cell[1] for key in given if (cell := split_row_key(key)) and cell[0] == self.rows_key}
        )
        cells = [row_key(self.rows_key, n, f.key) for n in numbers for f in self.row_fields]
        return [f.key for f in self.fields] + cells

    def json_schema(self) -> dict[str, Any]:
        """Schema der Antwort: je Feld ein Objekt aus `value` und `location`."""

        def schema_of(field: TemplateField) -> dict[str, Any]:
            return {
                "type": "object",
                "description": field.description,
                "properties": {
                    "value": {"type": ["string", "number", "boolean", "null"]},
                    "location": {"type": "string"},
                },
                "required": ["value", "location"],
                "additionalProperties": False,
            }

        properties = {f.key: schema_of(f) for f in self.fields}
        if self.rows_key:
            properties[self.rows_key] = {
                "type": "array",
                "maxItems": MAX_ROWS,
                "items": {
                    "type": "object",
                    "properties": {f.key: schema_of(f) for f in self.row_fields},
                    "required": [f.key for f in self.row_fields],
                    "additionalProperties": False,
                },
            }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    def hint(self) -> str:
        """Hinweis für Claude: eine Zeile je Feld."""
        lines = [f"- {f.key}: {f.description}" for f in self.fields]
        text = "Gesucht sind diese Felder:\n" + "\n".join(lines)
        if self.rows_key:
            rows = [f"  - {f.key}: {f.description}" for f in self.row_fields]
            text += (
                f"\n- {self.rows_key}: eine Liste, je Zeile des Dokuments ein Eintrag in der "
                "Reihenfolge des Dokuments, mit diesen Feldern:\n" + "\n".join(rows)
            )
        return text
