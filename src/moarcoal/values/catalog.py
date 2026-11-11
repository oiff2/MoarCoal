"""Wertekatalog und Wertedefinition (docs/grundgeruest.md, 3.3 und 3.4)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from moarcoal.values.model import Amount, Subject, TimeRef, Unit, ValueKey

if TYPE_CHECKING:
    from moarcoal.registration import ModuleState
    from moarcoal.values.calculation import Calculation


class TimeKind(StrEnum):
    """Zeitbezugsart eines Schlüssels: Zeitraumwert oder Stichtagswert."""

    PERIOD = "Zeitraum"
    KEY_DATE = "Stichtag"


@dataclass(frozen=True)
class CatalogEntry:
    """Ein Schlüssel im Wertekatalog."""

    key: ValueKey
    meaning: str
    unit: Unit
    time_kind: TimeKind
    has_subject: bool = False


@dataclass(frozen=True)
class ValueDefinition:
    """Katalogeintrag, Rechnung und (bei Werten mit Bezugsobjekt) Aufzählung der Bezugsobjekte."""

    entry: CatalogEntry
    compute: Callable[["Calculation"], Amount]
    subjects: Callable[["ModuleState", TimeRef], list[Subject]] | None = None


class CatalogError(ValueError):
    """Der Wertekatalog ist in sich widersprüchlich (Programmfehler beim Anmelden)."""


class UnknownValueKey(LookupError):
    """Ein Schlüssel, den kein Modul angemeldet hat (Programmfehler, nie eine Null)."""


@dataclass(frozen=True)
class ValueCatalog:
    """Alle Schlüssel, die Module anmelden."""

    definitions: dict[ValueKey, ValueDefinition]
    owners: dict[ValueKey, str]  # Schlüssel -> Modulschlüssel

    @classmethod
    def of(cls, modules: Iterable[tuple[str, tuple[ValueDefinition, ...]]]) -> "ValueCatalog":
        definitions: dict[ValueKey, ValueDefinition] = {}
        owners: dict[ValueKey, str] = {}
        for module_key, module_definitions in modules:
            for definition in module_definitions:
                key = definition.entry.key
                if key.module != module_key:
                    raise CatalogError(f"{key} gehört nicht zum Modul {module_key}")
                if key in definitions:
                    raise CatalogError(f"{key} ist mehrfach angemeldet")
                if definition.entry.has_subject != (definition.subjects is not None):
                    raise CatalogError(f"{key}: Bezugsobjekt und Aufzählung passen nicht zusammen")
                definitions[key] = definition
                owners[key] = module_key
        return cls(definitions, owners)

    def definition(self, key: str) -> ValueDefinition:
        try:
            return self.definitions[ValueKey(key)]
        except (KeyError, ValueError) as error:
            raise UnknownValueKey(f"unbekannter Schlüssel: {key!r}") from error

    def entries(self) -> list[CatalogEntry]:
        return [d.entry for d in self.definitions.values()]
