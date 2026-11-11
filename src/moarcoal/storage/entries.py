"""Einträge und Adressen (docs/grundgeruest.md, 3.1; ADR 0005)."""

import hashlib
import json
import secrets
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field

ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
ID_LENGTH = 10
ID_PATTERN = r"^[A-Z2-7]{10}$"


def new_id() -> str:
    """Zufällige Kennung (Base32), wird beim Bauen eines neuen Eintrags vergeben."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


class EntryAddress(BaseModel):
    """Wie ein Eintrag überall genannt wird: `<Art>:<Kennung>`, z. B. `Expense:7KQ2M3XA4T`."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]*$")
    id: str = Field(pattern=ID_PATTERN)

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"

    @classmethod
    def parse(cls, text: str) -> Self:
        kind, separator, id_ = text.partition(":")
        if not separator:
            raise ValueError(f"keine Adresse: {text!r}")
        return cls(kind=kind, id=id_)


class Entry(BaseModel):
    """Basis jeder Eintragsart. Die Art ist der Klassenname.

    Eine Unterklasse nennt in `file_schema` das Dateiformat (`<modul>/<n>`, ein Format je
    Datei) und in `path` die Datei (relativ zum Datenverzeichnis, mit `/`), in die sie
    gehört. Das ersetzt die Funktion Eintrag -> Pfad der Modulanmeldung, bis es diese gibt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_schema: ClassVar[str]

    id: str = Field(default_factory=new_id, pattern=ID_PATTERN)
    owner: str = Field(min_length=1)

    @property
    def address(self) -> EntryAddress:
        return EntryAddress(kind=type(self).__name__, id=self.id)

    def path(self) -> str:
        raise NotImplementedError(f"{type(self).__name__} muss `path` festlegen")


def entry_checksum(entry: Entry) -> str:
    """Prüfsumme des Eintrags; sie bringt das Formular mit und `apply` vergleicht sie."""
    canonical = json.dumps(entry.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def kind_collisions(classes: list[type[Entry]]) -> list[str]:
    """Namen von Arten, die mehrfach vorkommen (Arten sind über alle Module eindeutig)."""
    names = [cls.__name__ for cls in classes]
    return sorted({name for name in names if names.count(name) > 1})


def all_kinds(package: str = "moarcoal") -> list[type[Entry]]:
    """Alle Eintragsarten im App-Code (Unterklassen von `Entry`, auch indirekt)."""
    found: list[type[Entry]] = []
    todo = list(Entry.__subclasses__())
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        if cls.__module__.split(".")[0] == package:
            found.append(cls)
    return found
