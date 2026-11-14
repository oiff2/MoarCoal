"""Datenverzeichnis, Stand und Schreibweg (docs/grundgeruest.md, Abschnitt 5; ADR 0006).

Nur dieses Paket liest und schreibt Dateien. Der Schreibweg ist ein Vorgang aus Änderungen:
prüfen, Prüfsummen vergleichen, sichern nach `.backup/`, temporäre Dateien mit `fsync`,
umbenennen, Stand tauschen. Ein Journal über mehrere Dateien gibt es noch nicht: Scheitert das
Umbenennen mittendrin, stellt `apply` die schon ersetzten Dateien aus dem Speicher wieder her;
ein Absturz mitten im Umbenennen ist damit nicht abgedeckt.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from pydantic import ValidationError

from moarcoal.storage.aborted_extractions import ABORTED_EXTRACTION_KIND
from moarcoal.storage.dismissals import DISMISSAL_KIND
from moarcoal.storage.documents import document_entry_kind
from moarcoal.storage.entries import (
    Entry,
    EntryAddress,
    EntryKind,
    entry_checksum,
    falls_with,
    kind_collisions,
    strong_references,
    with_reference_moved,
)
from moarcoal.storage.expected_documents import EXPECTED_DOCUMENT_KIND
from moarcoal.storage.hidden_files import HIDDEN_FILE_KIND, HIDDEN_FOLDER_KIND
from moarcoal.storage.issuers import ISSUER_KIND
from moarcoal.storage.proposals import PROPOSAL_KIND
from moarcoal.storage.snapshots import SNAPSHOT_KIND

DEFAULT_DATA_DIR_NAME = "MoarCoal"
DATA_DIRS = ("users", "common")  # hier liegen Einträge; .backup, .cache und config nicht
BACKUP_DIR = ".backup"
BACKUP_KEEP = 20
TEMP_SUFFIX = ".tmp"
SITES_FILE = "common/sites.json"  # keine Einträge, sondern die benannten Ablageorte
SITES_SCHEMA = "ablageorte/1"
DERIVED_DENYLIST_FILE = "common/derived-denylist.txt"  # abgeleitet, nie von Hand
MAX_SITE_FILE_BYTES = 50_000_000


class StoreError(Exception):
    """Das Datenverzeichnis lässt sich nicht laden; die Meldung nennt die Datei."""


class SiteFileError(Exception):
    """Eine Datei an einem Ablageort lässt sich nicht lesen; die Meldung ist für den Nutzer."""


@dataclass(frozen=True)
class SiteFile:
    """Eine Datei an einem Ablageort: Ablageort, Pfad relativ dazu (mit `/`), Größe, SHA-256."""

    site: str
    path: str
    size: int
    sha256: str


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


@dataclass(frozen=True)
class Merge:
    """Eintrag `source` in Eintrag `into` derselben Art zusammenführen (bewusste Ausnahme).

    Geht nur bei Arten mit `EntryKind.merge` (bisher Aussteller), die das neue Ziel bildet; die
    Kennung der Quelle verweist danach auf das Ziel (`State.resolve`, `EntryKind.former_ids`),
    Einträge mit einem Feld auf die Quelle verweisen auf das Ziel. `expected` und `expected_into`
    sind die Prüfsummen der bekannten Fassungen.
    """

    source: EntryAddress
    into: EntryAddress
    expected: str
    expected_into: str

    @property
    def address(self) -> EntryAddress:
        return self.source


type Change = Put | Delete | Merge


@dataclass(frozen=True)
class Applied:
    changes: tuple[Change, ...]


@dataclass(frozen=True)
class Rejected:
    reasons: Mapping[EntryAddress, str]


@dataclass(frozen=True)
class State:
    """Alle geladenen Einträge, unveränderlich.

    `denylist_failed`: die abgeleitete Sperrliste ließ sich zuletzt nicht schreiben (Befund).
    `former`: frühere Adresse eines zusammengeführten Eintrags -> Adresse des heutigen Eintrags
    (der Store bildet sie aus `EntryKind.former_ids`).
    """

    entries: Mapping[EntryAddress, Entry]
    denylist_failed: bool = False
    former: Mapping[EntryAddress, EntryAddress] = field(
        default_factory=dict[EntryAddress, EntryAddress]
    )

    def get(self, address: EntryAddress) -> Entry | None:
        return self.entries.get(address)

    def resolve(self, address: EntryAddress) -> Entry | None:
        """Wie `get`; die Adresse eines zusammengeführten Eintrags liefert das Ziel."""
        found = self.entries.get(address)
        if found is not None:
            return found
        current = self.former.get(address)
        return None if current is None else self.entries.get(current)

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


def _reference_problems(
    changes: Sequence[Change],
    new_entries: Mapping[EntryAddress, Entry],
    kinds: Mapping[str, EntryKind],
) -> dict[EntryAddress, str]:
    """Verweise nach dem Vorgang: Gelöschtes wird nicht mehr verwendet (schwache Verweise der
    Art ausgenommen)."""
    problems: dict[EntryAddress, str] = {}
    for change in changes:
        if isinstance(change, Delete | Merge) and strong_references(
            new_entries.values(), change.address, kinds
        ):
            problems[change.address] = "Wird noch verwendet."
    return problems


def _safe_path(relative: str) -> bool:
    pure = PurePosixPath(relative)
    return (
        str(pure) == relative  # keine leeren oder "."-Teile, kein doppelter Schrägstrich
        and not pure.is_absolute()
        and ".." not in pure.parts
        and pure.suffix == ".json"
        and bool(pure.parts)
        and pure.parts[0] in DATA_DIRS
        and relative != SITES_FILE
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


_WINDOWS_DRIVE = re.compile(r"([A-Za-z]):[\\/]?(.*)", re.DOTALL)


def site_folder(text: str) -> Path:
    """Ordner eines Ablageorts; Windows-Pfad `G:\\Steuer` wird zum WSL-Pfad `/mnt/g/Steuer`."""
    match = _WINDOWS_DRIVE.fullmatch(text)
    if match is None:
        return Path(text)
    drive, rest = match.groups()
    parts = [part for part in re.split(r"[\\/]", rest) if part]
    return Path("/mnt", drive.lower(), *parts)


def _load_sites(root: Path) -> dict[str, Path]:
    """Ablageorte aus `common/sites.json`; fehlt die Datei, gibt es keine."""
    raw = _read_if_exists(root / SITES_FILE)
    if raw is None:
        return {}
    try:
        body = json.loads(raw)
        if body["schema"] != SITES_SCHEMA:
            raise ValueError(body["schema"])
        texts = {str(name): str(folder) for name, folder in body["sites"].items()}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise StoreError(f"{SITES_FILE}: keine gültige Liste der Ablageorte") from error
    sites = {name: site_folder(text) for name, text in texts.items()}
    for name, folder in sites.items():
        if not folder.is_absolute():
            raise StoreError(
                f"{SITES_FILE}: Ablageort {name}: „{texts[name]}“ ist kein absoluter Pfad; "
                f"gemeint ist vielleicht „/{texts[name]}“ (WSL) oder ein Windows-Pfad wie „G:\\…“."
            )
    return sites


class Store:
    def __init__(
        self, root: Path, kinds: Sequence[EntryKind], sites: Mapping[str, Path] | None = None
    ) -> None:
        self._root = root
        self._sites = dict(_load_sites(root) if sites is None else sites)
        self._kinds = {kind.model.__name__: kind for kind in kinds}
        self._lock = threading.Lock()
        self._file_checksums: dict[str, str] = {}
        self._site_hashes: dict[tuple[str, int, int], str] = {}  # (Datei, Größe, mtime) -> SHA-256
        self._state = State(MappingProxyType({}))
        self._load()
        entries = self._state.entries
        self._state = self._state_of(entries, denylist_failed=not self._write_denylist(entries))

    @property
    def root(self) -> Path:
        return self._root

    def state(self) -> State:
        return self._state

    def site_names(self) -> list[str]:
        return sorted(self._sites)

    def read_site_file(self, site: str, relative: str) -> bytes:
        """Inhalt einer Datei an einem Ablageort; es wird nur gelesen, nie geschrieben."""
        folder = self._sites.get(site)
        if folder is None:
            raise SiteFileError(f"Unbekannter Ablageort {site!r}.")
        pure = PurePosixPath(relative)
        if not relative or pure.is_absolute() or ".." in pure.parts:
            raise SiteFileError("Der Pfad muss relativ zum Ablageort sein, ohne „..“.")
        target = (folder / pure).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise SiteFileError("Der Pfad führt aus dem Ablageort hinaus.")
        try:
            if target.stat().st_size > MAX_SITE_FILE_BYTES:
                raise SiteFileError("Die Datei ist zu groß.")
            return target.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as error:
            raise SiteFileError(
                f"Am Ablageort {site!r} gibt es keine Datei {relative!r}."
            ) from error
        except OSError as error:
            raise SiteFileError(f"Die Datei lässt sich nicht lesen ({error.strerror}).") from error

    def list_site_files(self, site: str) -> list[SiteFile]:
        """Alle Dateien eines Ablageorts, rekursiv und nach Pfad sortiert; es wird nur gelesen.

        Es gelten die Regeln von `read_site_file`: Verzeichnis-Links werden nicht verfolgt, Dateien
        mit Ziel außerhalb des Ablageorts, zu große und unlesbare Dateien fehlen in der Liste.
        Ordner mit Punkt am Anfang (etwa `.git`) werden samt Inhalt übergangen.
        """
        folder = self._sites.get(site)
        if folder is None:
            raise SiteFileError(f"Unbekannter Ablageort {site!r}.")
        base = folder.resolve()
        found: list[SiteFile] = []
        for current, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                file = Path(current) / name
                try:
                    target = file.resolve()
                    if not target.is_relative_to(base) or not target.is_file():
                        continue
                    info = target.stat()
                    if info.st_size > MAX_SITE_FILE_BYTES:
                        continue
                    key = (str(target), info.st_size, info.st_mtime_ns)
                    sha256 = self._site_hashes.get(key)
                    if sha256 is None:
                        sha256 = self._site_hashes[key] = _sha256(target.read_bytes())
                except OSError:
                    continue
                relative = file.relative_to(base).as_posix()
                found.append(SiteFile(site, relative, info.st_size, sha256))
        return sorted(found, key=lambda f: f.path)

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
                if relative == SITES_FILE:
                    continue
                data = file.read_bytes()
                for entry in self._parse(relative, data):
                    if entry.address in entries:
                        raise StoreError(f"{relative}: {entry.address} kommt doppelt vor")
                    entries[entry.address] = entry
                self._file_checksums[relative] = _sha256(data)
        self._state = self._state_of(MappingProxyType(entries))

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
                case Merge(into=into):
                    reason = self._merge(change, state, new_entries, touch)
                    if reason is not None:
                        reasons[address] = reason
                        continue
                    seen.add(into)
            if current is not None:
                touch(self._path_of(current), address)
        along = self._fall_along(changes, new_entries, seen, touch)
        changes = (*changes, *along)
        if not reasons:
            reasons.update(_reference_problems(changes, new_entries, self._kinds))
            reasons.update(self._kind_problems(changes, new_entries))
        if reasons:
            return Rejected(reasons)

        plan = self._plan(new_entries, touched, reasons)
        if reasons:
            return Rejected(reasons)

        self._write(plan)
        entries = MappingProxyType(new_entries)
        self._state = self._state_of(entries, denylist_failed=not self._write_denylist(entries))
        return Applied(changes)

    def _fall_along(
        self,
        changes: Sequence[Change],
        new_entries: dict[EntryAddress, Entry],
        seen: set[EntryAddress],
        touch: Callable[[str, EntryAddress], None],
    ) -> list[Delete]:
        """Folge eines Löschens: Einträge, die mit dem gelöschten wegfallen
        (`EntryKind.falls_with`), auch über mehrere Stufen. Ein Eintrag, den der Vorgang selbst
        ändert, fällt nicht weg."""
        pending = [
            c.address for c in changes if isinstance(c, Delete) and c.address not in new_entries
        ]
        along: list[Delete] = []
        while pending:
            target = pending.pop()
            for address, entry in list(new_entries.items()):
                if address not in seen and falls_with(entry, target, self._kinds):
                    del new_entries[address]
                    touch(self._path_of(entry), address)
                    along.append(Delete(address, entry_checksum(entry)))
                    pending.append(address)
        return along

    def references_to(self, address: EntryAddress, *, with_derived: bool = False) -> list[Entry]:
        """Die Einträge, die das Löschen von `address` sperren: sie verwenden es, ohne mit ihm
        wegzufallen (schwache Verweise zählen nicht); nach Adresse sortiert. Mit `with_derived`
        auch die, die mit ihm wegfallen: alles, was an `address` hängt."""
        found = strong_references(self._state.entries.values(), address, self._kinds)
        if with_derived:
            return found
        return [e for e in found if not falls_with(e, address, self._kinds)]

    def _kind_problems(
        self, changes: Sequence[Change], new_entries: Mapping[EntryAddress, Entry]
    ) -> dict[EntryAddress, str]:
        """Prüfungen der Eintragsarten (`EntryKind.check`) für jeden geschriebenen Eintrag,
        gegen den Stand nach dem ganzen Vorgang."""
        problems: dict[EntryAddress, str] = {}
        for change in changes:
            address = change.into if isinstance(change, Merge) else change.address
            entry = new_entries.get(address)
            check = None if entry is None else self._kinds[type(entry).__name__].check
            if entry is not None and check is not None:
                reason = check(entry, new_entries)
                if reason is not None:
                    problems[address] = reason
        return problems

    def _merge(
        self,
        change: Merge,
        state: State,
        new_entries: dict[EntryAddress, Entry],
        touch: Callable[[str, EntryAddress], None],
    ) -> str | None:
        source, target = state.get(change.source), state.get(change.into)
        if source is None or target is None or type(source) is not type(target):
            return "Diese Einträge lassen sich nicht zusammenführen."
        merge = self._kinds[type(target).__name__].merge
        if merge is None:
            return "Diese Einträge lassen sich nicht zusammenführen."
        if source.address == target.address:
            return "Ein Eintrag lässt sich nicht mit sich selbst zusammenführen."
        if (
            entry_checksum(source) != change.expected
            or entry_checksum(target) != change.expected_into
        ):
            return "Inzwischen geändert."
        merged = merge(source, target)
        new_entries[merged.address] = merged
        touch(self._path_of(merged), merged.address)
        del new_entries[source.address]
        for address, entry in list(new_entries.items()):
            moved = with_reference_moved(entry, source.address, target.address)
            if moved is not entry:
                new_entries[address] = moved
                touch(self._path_of(entry), address)
        return None

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

    def _state_of(
        self, entries: Mapping[EntryAddress, Entry], denylist_failed: bool = False
    ) -> State:
        """Der Stand mit den früheren Adressen, die `EntryKind.former_ids` nennt."""
        former: dict[EntryAddress, EntryAddress] = {}
        for entry in entries.values():
            kind = self._kinds.get(type(entry).__name__)
            if kind is not None and kind.former_ids is not None:
                for old in kind.former_ids(entry):
                    former[EntryAddress(kind=entry.address.kind, id=old)] = entry.address
        return State(entries, denylist_failed, former)

    def _write_denylist(self, entries: Mapping[EntryAddress, Entry]) -> bool:
        """Schreibt die Sperrliste aus den sensiblen Feldern neu (Spec 8; `EntryKind.denylist`).

        Scheitert das, gilt der Vorgang trotzdem (ADR 0006): `False`, daraus wird über
        `State.denylist_failed` ein Befund, und die Warnung geht ins Protokoll.
        """
        lines: set[str] = set()
        for kind in self._kinds.values():
            if kind.denylist is not None:
                lines.update(kind.denylist([e for e in entries.values() if type(e) is kind.model]))
        data = "".join(f"{line}\n" for line in sorted(lines)).encode()
        target = self._root / DERIVED_DENYLIST_FILE
        try:
            if (_read_if_exists(target) or b"") != data:  # leer und fehlend ist dasselbe
                _write_file(target, data)
        except OSError:
            logging.getLogger(__name__).warning("Abgeleitete Sperrliste nicht geschrieben")
            return False
        return True

    def _backup(self, path: str, data: bytes) -> None:
        directory = self._root / BACKUP_DIR / path
        _write_file(directory / f"{time.time_ns():020d}.json", data)
        for old in sorted(directory.glob("*.json"))[:-BACKUP_KEEP]:
            old.unlink()


def open_store(
    root: Path,
    kinds: Sequence[EntryKind],
    sites: Mapping[str, Path] | None = None,
    once_per_period: Mapping[str, str] | None = None,
) -> Store:
    """Öffnet das Datenverzeichnis `root` (injizierbar) mit den angemeldeten Eintragsarten.

    Die Arten der Datenebene (Dokument, Aussteller, Ausblendungen, Erwarteter Beleg,
    Schnappschuss) kommen immer dazu.
    `sites` nennt die Ablageorte (Name -> Ordner); ohne Angabe gilt `common/sites.json`.
    `once_per_period` (Schlüssel -> Name) nennt die Dokumentarten mit nur einem Dokument je
    Bezugszeitraum und Nutzer; der Schreibweg weist ein zweites ab.
    """
    all_kinds = (
        document_entry_kind(once_per_period),
        DISMISSAL_KIND,
        HIDDEN_FILE_KIND,
        HIDDEN_FOLDER_KIND,
        ISSUER_KIND,
        EXPECTED_DOCUMENT_KIND,
        PROPOSAL_KIND,
        ABORTED_EXTRACTION_KIND,
        SNAPSHOT_KIND,
        *kinds,
    )
    collisions = kind_collisions([kind.model for kind in all_kinds])
    if collisions:
        raise StoreError(f"Arten nicht eindeutig: {', '.join(collisions)}")
    return Store(root, all_kinds, sites)
