"""Auslese-Vorlage: was ein Modul für eine Dokumentart auslesen lassen will (Spec 3.6, Abschnitt 7).

Die Vorlage nennt die Felder mit Schlüssel, Bezeichnung, Einheit und Hinweis für Claude und eine
Fassungsnummer. Daraus entstehen das JSON-Schema und der Hinweis für den `Extractor`.
"""

from dataclasses import dataclass
from typing import Any


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


@dataclass(frozen=True)
class ExtractionTemplate:
    """Felder einer Dokumentart, die Claude lesen soll, mit Fassungsnummer (`version`)."""

    version: int
    fields: tuple[TemplateField, ...]

    def __post_init__(self) -> None:
        keys = [field.key for field in self.fields]
        if not keys or len(set(keys)) != len(keys) or not all(keys):
            raise ValueError("Feldschlüssel der Vorlage müssen vorhanden und eindeutig sein")

    def field(self, key: str) -> TemplateField | None:
        return next((f for f in self.fields if f.key == key), None)

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

        return {
            "type": "object",
            "properties": {f.key: schema_of(f) for f in self.fields},
            "required": [f.key for f in self.fields],
            "additionalProperties": False,
        }

    def hint(self) -> str:
        """Hinweis für Claude: eine Zeile je Feld."""
        lines = [f"- {f.key}: {f.description}" for f in self.fields]
        return "Gesucht sind diese Felder:\n" + "\n".join(lines)
