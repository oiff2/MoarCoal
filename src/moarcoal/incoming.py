"""Der Eingang: Dateien der Ablageorte, die weder aufgenommen noch ausgeblendet sind (Spec 3.6).

Erkannt wird eine Datei am SHA-256; eine umbenannte, schon aufgenommene Datei ist nicht neu.
Aufgenommen wird nur über `take_in` (`documents.py`); hier steht das Auflisten und Ausblenden.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Delete,
    Document,
    HiddenFile,
    Put,
    Rejected,
    SiteFile,
    State,
    Store,
)


def all_site_files(store: Store) -> list[SiteFile]:
    """Alle Dateien aller Ablageorte."""
    return [file for site in store.site_names() for file in store.list_site_files(site)]


def incoming_files(files: Sequence[SiteFile], state: State, user: str) -> list[SiteFile]:
    """Der Eingang von `user`: nicht von ihm aufgenommen, nicht ausgeblendet.

    Gleicher Inhalt an mehreren Stellen erscheint einmal, mit dem ersten Pfad.
    """
    known = {d.sha256 for d in state.of_kind(Document) if d.owner == user}
    known |= {h.sha256 for h in state.of_kind(HiddenFile)}
    shown: dict[str, SiteFile] = {}
    for file in files:
        if file.sha256 not in known:
            shown.setdefault(file.sha256, file)
    return list(shown.values())


def hide_file(store: Store, file: SiteFile, note: str) -> Applied | Rejected:
    """Blendet die Datei für alle Nutzer aus; die Notiz ist freiwillig."""
    entry = HiddenFile(
        owner=COMMON_OWNER, sha256=file.sha256, site=file.site, path=file.path, note=note.strip()
    )
    return store.apply([Put(entry)])


def hidden_files(state: State) -> list[HiddenFile]:
    """Alle Ausblendungen im Eingang, nach Pfad sortiert (auch ohne Ablageort)."""
    return sorted(state.of_kind(HiddenFile), key=lambda h: (h.path, h.site, h.sha256))


def show_file(store: Store, hidden: HiddenFile, expected: str) -> Applied | Rejected:
    """Blendet die Datei wieder ein; `expected` ist die Prüfsumme der angezeigten Fassung."""
    return store.apply([Delete(hidden.address, expected=expected)])


STANDS = ("offen", "aufgenommen", "alle")


@dataclass(frozen=True)
class Row:
    """Eine Zeile der Ablage: die Datei, bei einer aufgenommenen auch ihr Dokument."""

    file: SiteFile
    document: Document | None = None

    @property
    def name(self) -> str:
        return self.file.path.rsplit("/", 1)[-1]


@dataclass
class Folder:
    """Ein Ordner der Ablage (der oberste ist der Ablageort). `waiting` zählt die offenen Dateien
    darunter, auch wenn der Filter sie nicht zeigt; `shown` die sichtbaren."""

    name: str
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


def ablage_rows(files: Sequence[SiteFile], state: State, user: str) -> list[Row]:
    """Alle Zeilen der Ablage von `user`: eine je Inhalt (mit dem ersten Pfad), ohne Ausgeblendete.

    Hat `user` den Inhalt aufgenommen, steht er mit seinem Dokument da, auch wenn ihn jemand
    ausgeblendet hat; so hat jede Datei genau eine Stelle (Ablage oder Ausgeblendet).
    """
    documents: dict[str, Document] = {}
    for document in state.of_kind(Document):
        if document.owner == user:
            documents.setdefault(document.sha256, document)
    hidden = {h.sha256 for h in state.of_kind(HiddenFile)}
    rows: dict[str, Row] = {}
    for file in files:
        if file.sha256 in documents or file.sha256 not in hidden:
            rows.setdefault(file.sha256, Row(file, documents.get(file.sha256)))
    return list(rows.values())


def hidden_section(hidden: Sequence[HiddenFile], rows: Sequence[Row]) -> list[HiddenFile]:
    """Die Ausblendungen des Abschnitts „Ausgeblendet“ (ohne Dateien, die in der Ablage stehen)."""
    in_tree = {r.file.sha256 for r in rows}
    return [h for h in hidden if h.sha256 not in in_tree]


def ablage_tree(rows: Sequence[Row], sites: Sequence[str], stand: str) -> list[Folder]:
    """Die Ablageorte als Bäume. Der Filter `stand` (offen, aufgenommen, alle) bestimmt, welche
    Dateien erscheinen; Ordner ohne sichtbare Datei fehlen."""
    roots = {site: Folder(site) for site in sites}
    for row in sorted(rows, key=lambda r: r.file.path):
        folder = roots.get(row.file.site)
        if folder is None:
            continue
        waiting = row.document is None
        visible = stand == "alle" or (stand == "offen") == waiting
        *parents, _ = row.file.path.split("/")
        path = [folder]
        for name in parents:
            folder = folder.folders.setdefault(name, Folder(name))
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
