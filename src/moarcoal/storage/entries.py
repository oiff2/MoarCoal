"""Einträge und Adressen (docs/grundgeruest.md, 3.1; ADR 0005)."""

import hashlib
import json
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Self, cast

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
    """Basis jeder Eintragsart. Die Art ist der Klassenname."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_id, pattern=ID_PATTERN)
    owner: str = Field(min_length=1)

    @property
    def address(self) -> EntryAddress:
        return EntryAddress(kind=type(self).__name__, id=self.id)


type EntryCheck = Callable[[Entry, Mapping[EntryAddress, Entry]], str | None]
"""Prüfung eines geschriebenen Eintrags gegen alle Einträge nach dem Vorgang; Text = Abweisung."""


@dataclass(frozen=True)
class EntryKind:
    """Eine Eintragsart, wie die Modulanmeldung sie nennt (docs/grundgeruest.md, 4 und 5.2).

    `schema` ist das Dateiformat (`<modul>/<n>`, ein Format je Datei); `path` ist die reine
    Funktion Eintrag -> Datei (relativ zum Datenverzeichnis, mit `/`). Was der Schreibweg je Art
    zusätzlich tut, steht hier (optional): `check` prüft jeden geschriebenen Eintrag nach dem
    ganzen Vorgang, `denylist` bildet aus allen Einträgen der Art die Werte der Sperrliste,
    `merge` führt zwei Einträge der Art zusammen (Quelle, Ziel -> neues Ziel), `former_ids` nennt
    die Kennungen früherer, zusammengeführter Einträge, die jetzt auf diesen auflösen.
    """

    model: type[Entry]
    schema: str
    path: Callable[[Entry], str]
    check: EntryCheck | None = None
    denylist: Callable[[list[Entry]], list[str]] | None = None
    merge: Callable[[Entry, Entry], Entry] | None = None
    former_ids: Callable[[Entry], Sequence[str]] | None = None


def entry_kind[E: Entry](
    model: type[E],
    schema: str,
    path: Callable[[E], str],
    *,
    check: Callable[[E, Mapping[EntryAddress, Entry]], str | None] | None = None,
    denylist: Callable[[list[E]], list[str]] | None = None,
    merge: Callable[[E, E], E] | None = None,
    former_ids: Callable[[E], Sequence[str]] | None = None,
) -> EntryKind:
    return EntryKind(
        model,
        schema,
        cast(Callable[[Entry], str], path),
        cast(EntryCheck | None, check),
        cast(Callable[[list[Entry]], list[str]] | None, denylist),
        cast(Callable[[Entry, Entry], Entry] | None, merge),
        cast(Callable[[Entry], Sequence[str]] | None, former_ids),
    )


def with_reference_moved(entry: Entry, old: EntryAddress, new: EntryAddress) -> Entry:
    """Der Eintrag, in dem jedes Feld mit der Adresse `old` auf `new` zeigt (nur direkte Felder)."""
    moved = {name: new for name in type(entry).model_fields if getattr(entry, name) == old}
    return entry.model_copy(update=moved) if moved else entry


def referenced_addresses(entry: Entry) -> set[EntryAddress]:
    """Alle Adressen, auf die Felder des Eintrags verweisen (auch in Listen und Teilmodellen)."""
    found: set[EntryAddress] = set()

    def walk(value: object) -> None:
        if isinstance(value, EntryAddress):
            found.add(value)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                walk(getattr(value, name))
        elif isinstance(value, list | tuple | set | frozenset):
            for item in cast(Iterable[object], value):
                walk(item)
        elif isinstance(value, dict):
            for item in cast(dict[object, object], value).values():
                walk(item)

    walk(entry)
    return found


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
