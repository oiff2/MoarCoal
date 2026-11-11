"""Datenverzeichnis, Stand und Schreibweg (docs/grundgeruest.md, Abschnitt 5; ADR 0006).

Nur dieses Paket liest und schreibt Dateien. Der Schreibweg ist ein Vorgang aus Änderungen:
prüfen, Prüfsummen vergleichen, sichern nach `.backup/`, temporäre Dateien mit `fsync`,
umbenennen, Stand tauschen. Ein Journal über mehrere Dateien gibt es noch nicht: Scheitert das
Umbenennen mittendrin, stellt `apply` die schon ersetzten Dateien aus dem Speicher wieder her;
ein Absturz mitten im Umbenennen ist damit nicht abgedeckt.
"""

import hashlib
import json
import os
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from pydantic import ValidationError

from moarcoal.storage.entries import (
    Entry,
    EntryAddress,
    EntryKind,
    entry_checksum,
    kind_collisions,
)

DEFAULT_DATA_DIR_NAME = "MoarCoal"
DATA_DIRS = ("nutzer", "gemeinsam")  # hier liegen Einträge; .backup, .cache und config nicht
BACKUP_DIR = ".backup"
BACKUP_KEEP = 20
TEMP_SUFFIX = ".tmp"


class StoreError(Exception):
    """Das Datenverzeichnis lässt sich nicht laden; die Meldung nennt die Datei."""


@dataclass(frozen=True)
class Put:
    """Eintrag anlegen (`expected=None`) oder ersetzen (Prüfsumme der bekannten Fassung)."""

    entry: Entry
    expected: str | None = None

    @property
    def address(self) -> EntryAddress:
        return self.entry.address


@dataclass(frozen=True)
class Delete:
    """Eintrag löschen; `expected` ist die Prüfsumme der bekannten Fassung."""

    target: EntryAddress
    expected: str

    @property
    def address(self) -> EntryAddress:
        return self.target


type Change = Put | Delete


@dataclass(frozen=True)
class Applied:
    changes: tuple[Change, ...]


@dataclass(frozen=True)
class Rejected:
    reasons: Mapping[EntryAddress, str]


@dataclass(frozen=True)
class State:
    """Alle geladenen Einträge, unveränderlich."""

    entries: Mapping[EntryAddress, Entry]

    def get(self, address: EntryAddress) -> Entry | None:
        return self.entries.get(address)

    def of_kind[E: Entry](self, kind: type[E]) -> list[E]:
        return [e for e in self.entries.values() if type(e) is kind]

    def checksum(self, address: EntryAddress) -> str | None:
        entry = self.entries.get(address)
        return None if entry is None else entry_checksum(entry)


def default_data_dir() -> Path:
    return Path.home() / DEFAULT_DATA_DIR_NAME


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_if_exists(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _render(schema: str, entries: Sequence[Entry]) -> bytes:
    body = {
        "schema": schema,
        "entries": {
            str(e.address): e.model_dump(mode="json") for e in sorted(entries, key=_sort_key)
        },
    }
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sort_key(entry: Entry) -> str:
    return str(entry.address)


def _safe_path(relative: str) -> bool:
    pure = PurePosixPath(relative)
    return (
        str(pure) == relative  # keine leeren oder "."-Teile, kein doppelter Schrägstrich
        and not pure.is_absolute()
        and ".." not in pure.parts
        and pure.suffix == ".json"
        and bool(pure.parts)
        and pure.parts[0] in DATA_DIRS
    )


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file(target: Path, data: bytes) -> None:
    """Temporäre Datei mit fsync, dann umbenennen."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + TEMP_SUFFIX)
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    _fsync_dir(target.parent)


def _restore_file(target: Path, original: bytes | None) -> None:
    if original is None:
        target.unlink(missing_ok=True)
    else:
        _write_file(target, original)


class Store:
    def __init__(self, root: Path, kinds: Sequence[EntryKind]) -> None:
        self._root = root
        self._kinds = {kind.model.__name__: kind for kind in kinds}
        self._lock = threading.Lock()
        self._file_checksums: dict[str, str] = {}
        self._state = State(MappingProxyType({}))
        self._load()

    @property
    def root(self) -> Path:
        return self._root

    def state(self) -> State:
        return self._state

    def _path_of(self, entry: Entry) -> str:
        return self._kinds[type(entry).__name__].path(entry)

    # --- Laden ------------------------------------------------------------------------------

    def _load(self) -> None:
        for top in DATA_DIRS:
            for temp in sorted((self._root / top).rglob(f"*{TEMP_SUFFIX}")):
                temp.unlink()  # Rest eines abgebrochenen Schreibens; die echte Datei ist ganz
        entries: dict[EntryAddress, Entry] = {}
        for top in DATA_DIRS:
            for file in sorted((self._root / top).rglob("*.json")):
                relative = file.relative_to(self._root).as_posix()
                data = file.read_bytes()
                for entry in self._parse(relative, data):
                    if entry.address in entries:
                        raise StoreError(f"{relative}: {entry.address} kommt doppelt vor")
                    entries[entry.address] = entry
                self._file_checksums[relative] = _sha256(data)
        self._state = State(MappingProxyType(entries))

    def _parse(self, relative: str, data: bytes) -> list[Entry]:
        try:
            body = json.loads(data)
            schema = body["schema"]
            raw_entries = body["entries"]
        except (ValueError, KeyError, TypeError) as error:
            raise StoreError(f"{relative}: keine gültige MoarCoal-Datei") from error
        entries: list[Entry] = []
        for key, fields in raw_entries.items():
            try:
                address = EntryAddress.parse(key)
                kind = self._kinds.get(address.kind)
                if kind is None:
                    raise StoreError(f"{relative}: unbekannte Art {address.kind!r}")
                entry = kind.model.model_validate(fields)
            except (ValueError, ValidationError) as error:
                raise StoreError(f"{relative}: Eintrag {key} ist ungültig") from error
            if entry.address != address or kind.path(entry) != relative:
                raise StoreError(f"{relative}: Eintrag {key} gehört nicht in diese Datei")
            if schema != kind.schema:
                raise StoreError(f"{relative}: Format {schema!r}, erwartet {kind.schema!r}")
            entries.append(entry)
        return entries

    # --- Schreiben --------------------------------------------------------------------------

    def apply(self, changes: Sequence[Change]) -> Applied | Rejected:
        with self._lock:
            return self._apply(tuple(changes))

    def _apply(self, changes: tuple[Change, ...]) -> Applied | Rejected:
        state = self._state
        reasons: dict[EntryAddress, str] = {}
        new_entries = dict(state.entries)
        touched: dict[str, list[EntryAddress]] = {}  # Dateipfad -> Adressen der Änderungen

        def touch(path: str, address: EntryAddress) -> None:
            touched.setdefault(path, []).append(address)

        seen: set[EntryAddress] = set()
        for change in changes:
            address = change.address
            if address in seen:
                reasons[address] = "Mehrfach im selben Vorgang."
                continue
            seen.add(address)
            current = state.get(address)
            match change:
                case Put(entry=entry, expected=expected):
                    reason = self._check_put(entry, expected, current)
                    if reason is not None:
                        reasons[address] = reason
                        continue
                    valid = type(entry).model_validate(entry.model_dump())
                    new_entries[address] = valid
                    touch(self._path_of(valid), address)
                case Delete(expected=expected):
                    if current is None:
                        reasons[address] = "Eintrag existiert nicht."
                        continue
                    if entry_checksum(current) != expected:
                        reasons[address] = "Inzwischen geändert."
                        continue
                    del new_entries[address]
            if current is not None:
                touch(self._path_of(current), address)
        if reasons:
            return Rejected(reasons)

        plan = self._plan(new_entries, touched, reasons)
        if reasons:
            return Rejected(reasons)

        self._write(plan)
        self._state = State(MappingProxyType(new_entries))
        return Applied(changes)

    def _check_put(self, entry: Entry, expected: str | None, current: Entry | None) -> str | None:
        cls = type(entry)
        kind = self._kinds.get(cls.__name__)
        if kind is None or kind.model is not cls:
            return f"Unbekannte Art {cls.__name__}."
        try:
            valid = cls.model_validate(entry.model_dump())
            path = kind.path(valid)
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
            )
            return f"Prüfung fehlgeschlagen ({details})."
        if not _safe_path(path):
            return "Ungültiger Dateipfad für den Eintrag."
        if expected is None:
            return "Eintrag existiert schon." if current is not None else None
        if current is None:
            return "Eintrag existiert nicht mehr."
        if entry_checksum(current) != expected:
            return "Inzwischen geändert."
        return None

    def _plan(
        self,
        new_entries: Mapping[EntryAddress, Entry],
        touched: Mapping[str, list[EntryAddress]],
        reasons: dict[EntryAddress, str],
    ) -> dict[str, bytes | None]:
        """Neuer Inhalt je betroffener Datei (`None`: Datei entfällt, weil sie leer wird)."""
        plan: dict[str, bytes | None] = {}
        for path, addresses in touched.items():
            on_disk = _read_if_exists(self._root / path)
            actual = None if on_disk is None else _sha256(on_disk)
            if actual != self._file_checksums.get(path):
                for address in addresses:
                    reasons[address] = "Datei wurde von Hand geändert."
                continue
            members = [e for e in new_entries.values() if self._path_of(e) == path]
            schemas = {self._kinds[type(e).__name__].schema for e in members}
            if len(schemas) > 1:
                for address in addresses:
                    reasons[address] = "Arten mit verschiedenem Dateiformat in einer Datei."
                continue
            plan[path] = _render(schemas.pop(), members) if members else None
        return plan

    def _write(self, plan: Mapping[str, bytes | None]) -> None:
        originals = {path: _read_if_exists(self._root / path) for path in plan}
        for path, original in originals.items():
            if original is not None:
                self._backup(path, original)
        done: list[str] = []
        try:
            for path, data in plan.items():
                target = self._root / path
                if data is None:
                    target.unlink()
                else:
                    _write_file(target, data)
                done.append(path)
        except BaseException:
            for path in done:
                _restore_file(self._root / path, originals[path])
            raise
        for path, data in plan.items():
            if data is None:
                self._file_checksums.pop(path, None)
            else:
                self._file_checksums[path] = _sha256(data)

    def _backup(self, path: str, data: bytes) -> None:
        directory = self._root / BACKUP_DIR / path
        _write_file(directory / f"{time.time_ns():020d}.json", data)
        for old in sorted(directory.glob("*.json"))[:-BACKUP_KEEP]:
            old.unlink()


def open_store(root: Path, kinds: Sequence[EntryKind]) -> Store:
    """Öffnet das Datenverzeichnis `root` (injizierbar) mit den angemeldeten Eintragsarten."""
    collisions = kind_collisions([kind.model for kind in kinds])
    if collisions:
        raise StoreError(f"Arten nicht eindeutig: {', '.join(collisions)}")
    return Store(root, kinds)
