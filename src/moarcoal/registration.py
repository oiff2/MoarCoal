"""Modulanmeldung und eingegrenzter Stand eines Moduls (docs/grundgeruest.md, 3.4 und 4)."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

from moarcoal.documents import DocumentKind
from moarcoal.storage import Document, Entry, EntryAddress, EntryKind, State, entry_checksum
from moarcoal.values.catalog import ValueDefinition


@dataclass(frozen=True)
class ModuleRegistration:
    """Was ein Modul beim Start über sich bekannt gibt: Schlüssel, Name, Seiten, Arten, Werte.

    Je Art nennt `kinds` Dateiformat und die Funktion Eintrag -> Pfad; die Datenebene lädt und
    schreibt danach, das Modul fasst keine Datei an.
    """

    key: str
    area_name: str
    nav_label: str
    nav_url: str
    router: APIRouter
    kinds: tuple[EntryKind, ...]
    values: tuple[ValueDefinition, ...] = ()
    entry_url: Callable[[EntryAddress], str | None] = lambda address: None
    document_kinds: tuple[DocumentKind, ...] = ()


class ForeignKindError(LookupError):
    """Ein Modul hat nach einer Art gefragt, die ihm nicht gehört (Programmfehler)."""


class ModuleState:
    """Stand, eingegrenzt auf ein Modul und einen Nutzer; nur lesen."""

    def __init__(self, state: State, registration: ModuleRegistration, user: str) -> None:
        self._state = state
        self._kinds = {kind.model.__name__ for kind in registration.kinds}
        self._user = user

    @property
    def user(self) -> str:
        return self._user

    def _own(self, kind_name: str) -> None:
        if kind_name not in self._kinds:
            raise ForeignKindError(f"Art {kind_name} gehört nicht zu diesem Modul")

    def all[E: Entry](self, kind: type[E]) -> list[E]:
        """Alle Einträge einer eigenen Art des Nutzers, nach Adresse sortiert."""
        self._own(kind.__name__)
        found = [e for e in self._state.of_kind(kind) if e.owner == self._user]
        return sorted(found, key=lambda e: str(e.address))

    def get(self, address: EntryAddress) -> Entry | None:
        """Ein eigener Eintrag des Nutzers; Einträge anderer Nutzer gibt es hier nicht."""
        self._own(address.kind)
        entry = self._state.get(address)
        return entry if entry is not None and entry.owner == self._user else None

    def documents(self, document_kind: str | None = None) -> list[Document]:
        """Dokumente des Nutzers (Baustein der Datenebene), ggf. nur einer Dokumentart."""
        found = [d for d in self._state.of_kind(Document) if d.owner == self._user]
        if document_kind is not None:
            found = [d for d in found if d.document_kind == document_kind]
        return sorted(found, key=lambda d: str(d.address))

    def checksum(self, address: EntryAddress) -> str | None:
        entry = self.get(address)
        return None if entry is None else entry_checksum(entry)
