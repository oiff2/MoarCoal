"""Seitenmodell der Ablage: Zeilen, Baum, Filter nach Stand und Ausgeblendete (Reiter Ablage).

Was offen ist und wie man ausblendet, steht in `incoming.py`; hier steht, wie die Seite es zeigt.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from moarcoal.incoming import all_site_files, hidden_files, hidden_folders, in_hidden_folder
from moarcoal.links import document_file_url, site_file_url
from moarcoal.storage import (
    Document,
    HiddenFile,
    HiddenFolder,
    SiteFile,
    State,
    Store,
    entry_checksum,
)


class IntakeFilter(StrEnum):
    """Filter der Ablage nach Stand (URL-Parameter `stand`); voreingestellt offen, der Eingang."""

    OPEN = "offen"
    TAKEN_IN = "aufgenommen"
    ALL = "alle"

    @classmethod
    def of(cls, text: str) -> "IntakeFilter":
        """Der Filter zu `text`; Unbekanntes gilt als offen."""
        return next((f for f in cls if f.value == text), cls.OPEN)

    def shows(self, waiting: bool) -> bool:
        """Zeigt der Filter eine offene (`waiting`) bzw. aufgenommene Datei?"""
        return self == IntakeFilter.ALL or (self == IntakeFilter.OPEN) == waiting


@dataclass(frozen=True)
class Row:
    """Eine Zeile der Ablage: die Datei, bei einer aufgenommenen auch ihr Dokument."""

    file: SiteFile
    document: Document | None = None

    @property
    def name(self) -> str:
        return self.file.path.rsplit("/", 1)[-1]

    @property
    def path(self) -> str:
        return self.file.path

    @property
    def preview_url(self) -> str:
        if self.document is not None:
            return document_file_url(self.document.id)
        return site_file_url(self.file.sha256)


@dataclass(frozen=True)
class HiddenFileRow:
    """Eine Zeile im Abschnitt „Ausgeblendet“: die Ausblendung, ihre Prüfsumme und die Datei,
    falls sie noch in einem Ablageort liegt (sonst keine Größe und keine Vorschau)."""

    entry: HiddenFile
    checksum: str
    file: SiteFile | None

    @property
    def path(self) -> str:
        return self.entry.path

    @property
    def preview_url(self) -> str:
        return site_file_url(self.entry.sha256) if self.file else ""


@dataclass(frozen=True)
class HiddenFolderRow:
    """Ein ausgeblendeter Ordner mit seiner Prüfsumme und der Zahl der Dateien darunter."""

    entry: HiddenFolder
    checksum: str
    count: int


@dataclass
class Folder:
    """Ein Ordner der Ablage (der oberste ist der Ablageort). `waiting` zählt die offenen Dateien
    darunter, auch wenn der Filter sie nicht zeigt; `shown` die sichtbaren."""

    name: str
    site: str = ""
    path: str = ""  # relativ zum Ablageort; beim obersten leer
    folders: dict[str, "Folder"] = field(default_factory=lambda: dict[str, Folder]())
    rows: list[Row] = field(default_factory=list[Row])
    waiting: int = 0
    shown: int = 0

    def walk(self) -> Iterator[Row]:
        """Die sichtbaren Dateien in der Reihenfolge der Anzeige (erst Ordner, dann Dateien)."""
        for folder in self.folders.values():
            yield from folder.walk()
        yield from self.rows

    def contains(self, sha256: str) -> bool:
        return any(row.file.sha256 == sha256 for row in self.walk())


def next_open(tree: Sequence[Folder], sha256: str) -> str | None:
    """SHA-256 der nächsten Datei nach `sha256` im Baum (des Filters „offen“), am Ende von vorn;
    ohne weitere Datei `None`."""
    shas = [row.file.sha256 for root in tree for row in root.walk()]
    start = shas.index(sha256) + 1 if sha256 in shas else 0
    others = [s for s in shas[start:] + shas[:start] if s != sha256]
    return others[0] if others else None


def site_rows(files: Sequence[SiteFile], state: State, user: str) -> list[Row]:
    """Alle Zeilen der Ablage von `user`: eine je Inhalt (mit dem ersten Pfad), ohne Ausgeblendete.

    Hat `user` den Inhalt aufgenommen, steht er mit seinem Dokument da, auch wenn ihn jemand
    ausgeblendet hat; so hat jede Datei genau eine Stelle (Ablage oder Ausgeblendet).
    """
    documents: dict[str, Document] = {}
    for document in state.of_kind(Document):
        if document.owner == user:
            documents.setdefault(document.sha256, document)
    hidden = {h.sha256 for h in state.of_kind(HiddenFile)}
    folders = state.of_kind(HiddenFolder)
    rows: dict[str, Row] = {}
    for file in files:
        if file.sha256 in documents or (
            file.sha256 not in hidden and not in_hidden_folder(file, folders)
        ):
            rows.setdefault(file.sha256, Row(file, documents.get(file.sha256)))
    return list(rows.values())


def site_tree(
    rows: Sequence[Row], sites: Sequence[str], intake_filter: IntakeFilter
) -> list[Folder]:
    """Die Ablageorte als Bäume. Der Filter bestimmt, welche Dateien erscheinen; Ordner ohne
    sichtbare Datei fehlen."""
    roots = {site: Folder(site, site) for site in sites}
    for row in sorted(rows, key=lambda r: r.file.path):
        folder = roots.get(row.file.site)
        if folder is None:
            continue
        waiting = row.document is None
        visible = intake_filter.shows(waiting)
        *parents, _ = row.file.path.split("/")
        path = [folder]
        for name in parents:
            sub = f"{folder.path}/{name}" if folder.path else name
            folder = folder.folders.setdefault(name, Folder(name, row.file.site, sub))
            path.append(folder)
        for node in path:
            node.waiting += waiting
            node.shown += visible
        if visible:
            folder.rows.append(row)
    return [_pruned(root) for root in roots.values()]


def _pruned(folder: Folder) -> Folder:
    kept = {n: _pruned(f) for n, f in sorted(folder.folders.items()) if f.shown}
    folder.folders = kept
    return folder


@dataclass(frozen=True)
class SiteListing:
    """Die Ablage einer Anfrage, einmal aus den Dateien aller Ablageorte gebaut: Zeilen und
    Ausgeblendete (Dateien ohne die, die in der Ablage stehen, und Ordner)."""

    files: list[SiteFile]
    sites: list[str]
    rows: list[Row]
    hidden_files: list[HiddenFileRow]
    hidden_folders: list[HiddenFolderRow]

    def tree(self, intake_filter: IntakeFilter) -> list[Folder]:
        return site_tree(self.rows, self.sites, intake_filter)

    def open_files(self) -> list[SiteFile]:
        """Der Eingang (wie `incoming_files`)."""
        return [row.file for row in self.rows if row.document is None]

    def open_file(self, sha256: str) -> SiteFile | None:
        return next((f for f in self.open_files() if f.sha256 == sha256), None)

    def row(self, sha256: str) -> Row | None:
        return next((r for r in self.rows if r.file.sha256 == sha256), None)

    def hidden_file(self, sha256: str) -> HiddenFileRow | None:
        return next((h for h in self.hidden_files if h.entry.sha256 == sha256), None)


def site_listing(store: Store, state: State, user: str) -> SiteListing:
    """Die Ablage von `user` auf dem Stand `state`."""
    files = all_site_files(store)
    rows = site_rows(files, state, user)
    by_sha = {f.sha256: f for f in files}
    in_tree = {r.file.sha256 for r in rows}
    return SiteListing(
        files=files,
        sites=store.site_names(),
        rows=rows,
        hidden_files=[
            HiddenFileRow(h, entry_checksum(h), by_sha.get(h.sha256))
            for h in hidden_files(state)
            if h.sha256 not in in_tree
        ],
        hidden_folders=[
            HiddenFolderRow(h, entry_checksum(h), sum(1 for f in files if in_hidden_folder(f, [h])))
            for h in hidden_folders(state)
        ],
    )
