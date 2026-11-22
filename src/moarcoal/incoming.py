"""Der Eingang: Dateien der Ablageorte, die weder aufgenommen noch ausgeblendet sind (Spec 3.6).

Erkannt wird eine Datei am SHA-256; eine umbenannte, schon aufgenommene Datei ist nicht neu.
Aufgenommen wird nur über `take_in` (`documents.py`); hier steht das Auflisten und Ausblenden.
"""

from collections.abc import Sequence
from enum import StrEnum

from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Delete,
    Document,
    HiddenFile,
    HiddenFolder,
    Put,
    Rejected,
    SiteFile,
    State,
    Store,
    entry_checksum,
)
from moarcoal.storage.sites import path_error
from moarcoal.values.findings import Finding, Severity

MISSING_FILE = "document_file_missing"  # Befundart: die Datei eines Dokuments fehlt


def all_site_files(store: Store) -> list[SiteFile]:
    """Alle Dateien aller Ablageorte."""
    return [file for site in store.sites.names() for file in store.sites.files(site)]


class Classification(StrEnum):
    """Die eine Einordnung jeder Datei der Ablageorte für einen Nutzer."""

    OPEN = "open"  # im Eingang
    TAKEN = "taken"  # von ihm aufgenommen (auch wenn sie jemand ausgeblendet hat)
    HIDDEN = "hidden"  # ausgeblendet, nicht aufgenommen
    IN_HIDDEN_FOLDER = "in_hidden_folder"  # unter einem ausgeblendeten Ordner, nicht aufgenommen
    SAME_CONTENT = "same_content"  # gleicher Inhalt wie ein Dokument, anderer Ort (Hinweis)


class Unavailable(StrEnum):
    """Warum eine angezeigte Datei nicht mehr aufgenommen werden kann (`Incoming.resolve`)."""

    MISSING = "missing"  # unter Ablageort und Pfad liegt nichts mehr
    CHANGED = "changed"  # dort liegt jetzt ein anderer Inhalt
    NOT_OPEN = "not_open"  # derselbe Inhalt, aber nicht mehr im Eingang


class Incoming:
    """Der Eingang eines Nutzers auf einem Stand: ordnet jede Datei der Ablageorte genau einer
    Klasse zu (`Classification`) und sagt je Dokument, ob seine Datei da, verschoben oder fehlend
    ist. Die einzige Stelle, die „aufgenommen schlägt ausgeblendet“, „im ausgeblendeten Ordner“,
    „gleicher Inhalt“ und „verschoben“ herleitet (Spec 3.6, ADR 0003); alle anderen lesen nur.

    Gleicher Inhalt (SHA-256) zählt für `open_files` einmal, mit dem ersten Pfad.
    """

    def __init__(self, files: Sequence[SiteFile], state: State, user: str) -> None:
        self.files: tuple[SiteFile, ...] = tuple(files)
        self._state = state
        self._documents = sorted(state.of_kind(Document), key=lambda d: (d.path, d.site, d.id))
        self._taken: dict[str, Document] = {}  # SHA-256 -> erstes Dokument von `user` nach Pfad
        for d in self._documents:
            if d.owner == user:
                self._taken.setdefault(d.sha256, d)
        self._hidden = {h.sha256 for h in state.of_kind(HiddenFile)}
        self._folders = state.of_kind(HiddenFolder)
        self._at = {(f.site, f.path): f for f in self.files}
        self._present = {(f.site, f.path, f.sha256) for f in self.files}
        self._first_path: dict[tuple[str, str], str] = {}  # (Ablageort, SHA-256) -> erster Pfad
        for f in self.files:
            self._first_path.setdefault((f.site, f.sha256), f.path)

    def classify(self, file: SiteFile) -> Classification:
        """Die Klasse einer Datei der Ablageorte."""
        if (document := self._taken.get(file.sha256)) is not None:
            if (file.site, file.path) == (document.site, document.path):
                return Classification.TAKEN
            if self._is_moved_file(document, file) or self._is_hidden(file):
                return Classification.TAKEN  # die Datei des Dokuments selbst oder ausgeblendet
            return Classification.SAME_CONTENT
        if file.sha256 in self._hidden:
            return Classification.HIDDEN
        if _in_hidden_folders(file, self._folders):
            return Classification.IN_HIDDEN_FOLDER
        return Classification.OPEN

    def _is_hidden(self, file: SiteFile) -> bool:
        return file.sha256 in self._hidden or _in_hidden_folders(file, self._folders)

    def _is_moved_file(self, document: Document, file: SiteFile) -> bool:
        """Ist `file` der neue Ort der Datei von `document` (verschoben im selben Ablageort)?"""
        return (
            file.site == document.site
            and (document.site, document.path, document.sha256) not in self._present
        )

    def open_files(self, sites: Sequence[str] | None = None) -> list[SiteFile]:
        """Die offenen Dateien, je Inhalt eine (die erste). `sites`: nur diese Ablageorte, in dieser
        Reihenfolge (der erste Ort gewinnt); ohne Angabe alle in der Reihenfolge der Dateien."""
        shown: dict[str, SiteFile] = {}
        for file in self._in(sites):
            if self.classify(file) is Classification.OPEN:
                shown.setdefault(file.sha256, file)
        return list(shown.values())

    def same_content(self, sites: Sequence[str] | None = None) -> list[tuple[SiteFile, Document]]:
        """Je Datei mit gleichem Inhalt wie ein Dokument des Nutzers (bei mehreren das erste nach
        Pfad) dieses Dokument; `sites` wie bei `open_files`."""
        return [
            (file, self._taken[file.sha256])
            for file in self._in(sites)
            if self.classify(file) is Classification.SAME_CONTENT
        ]

    def is_taken(self, sha256: str) -> bool:
        """Hat der Nutzer ein Dokument mit diesem Inhalt?"""
        return sha256 in self._taken

    def file_with(self, sha256: str) -> SiteFile | None:
        """Die erste Datei der Ablageorte mit diesem Inhalt."""
        return next((f for f in self.files if f.sha256 == sha256), None)

    def count_under(self, folder: HiddenFolder) -> int:
        """Wie viele Dateien unter dem Ordner liegen."""
        return sum(1 for f in self.files if _in_hidden_folders(f, [folder]))

    def resolve(self, site: str, path: str, sha256: str) -> SiteFile | Unavailable:
        """Die angezeigte Datei (Ablageort, Pfad, SHA-256), wenn sie noch offen ist, sonst warum
        nicht."""
        current = self._at.get((site, path))
        if current is None:
            return Unavailable.MISSING
        if current.sha256 != sha256:
            return Unavailable.CHANGED
        if self.classify(current) is not Classification.OPEN:
            return Unavailable.NOT_OPEN
        return current

    def missing_documents(self, user: str) -> list[Document]:
        """Die Dokumente von `user`, deren Datei weder unter ihrem Pfad noch unter einem anderen
        Pfad desselben Ablageorts liegt, nach Ablageort und Pfad."""
        return [
            d
            for d in sorted(self._documents, key=lambda d: (d.site, d.path))
            if d.owner == user and self._file_state(d) is None
        ]

    def moved_documents(self) -> list[tuple[Document, str]]:
        """Die Dokumente aller Nutzer, deren Datei im selben Ablageort unter anderem Pfad liegt,
        mit dem neuen (ersten) Pfad, nach Ablageort und Pfad."""
        moved: list[tuple[Document, str]] = []
        for d in sorted(self._documents, key=lambda d: (d.site, d.path)):
            new_path = self._file_state(d)
            if new_path is not None and new_path != d.path:
                moved.append((d, new_path))
        return moved

    def _file_state(self, document: Document) -> str | None:
        """Der Pfad der Datei des Dokuments (der eigene, wenn sie dort liegt), `None`, wenn sie im
        Ablageort fehlt."""
        if (document.site, document.path, document.sha256) in self._present:
            return document.path
        return self._first_path.get((document.site, document.sha256))

    def _in(self, sites: Sequence[str] | None) -> list[SiteFile]:
        if sites is None:
            return list(self.files)
        return [f for site in sites for f in self.files if f.site == site]


def _in_hidden_folders(file: SiteFile, folders: Sequence[HiddenFolder]) -> bool:
    """Liegt die Datei unter einem ausgeblendeten Ordner ihres Ablageorts (beliebig tief)?"""
    return any(f.site == file.site and file.path.startswith(f.path + "/") for f in folders)


def folder_path_error(files: Sequence[SiteFile], site: str, path: str) -> str | None:
    """Warum `path` kein Ordner von `site` ist, den man ausblenden kann; `None`, wenn er einer ist.

    Es gilt die Pfadregel der Ablageorte (`path_error`). Als Ordner gilt, was mindestens eine
    aufgelistete Datei enthält; aufgelistet ist nur, was im Ablageort liegt.
    """
    if (error := path_error(path)) is not None:
        return error
    if not any(f.site == site and f.path.startswith(path + "/") for f in files):
        return "Diesen Ordner gibt es im Ablageort nicht."
    return None


def hide_folder(store: Store, state: State, site: str, path: str) -> Applied | Rejected | None:
    """Blendet den Ordner mit allem darunter für alle Nutzer aus; war er es schon, geschieht
    nichts (`None`). Der Pfad muss vorher mit `folder_path_error` geprüft sein."""
    if any(h.site == site and h.path == path for h in state.of_kind(HiddenFolder)):
        return None
    return store.apply([Put(HiddenFolder(owner=COMMON_OWNER, site=site, path=path))])


def hidden_folders(state: State) -> list[HiddenFolder]:
    """Alle ausgeblendeten Ordner, nach Ablageort und Pfad sortiert."""
    return sorted(state.of_kind(HiddenFolder), key=lambda h: (h.site, h.path))


def hide_file(store: Store, file: SiteFile, note: str) -> Applied | Rejected:
    """Blendet die Datei für alle Nutzer aus; die Notiz ist freiwillig."""
    entry = HiddenFile(
        owner=COMMON_OWNER, sha256=file.sha256, site=file.site, path=file.path, note=note.strip()
    )
    return store.apply([Put(entry)])


def hidden_files(state: State) -> list[HiddenFile]:
    """Alle Ausblendungen im Eingang, nach Pfad sortiert (auch ohne Ablageort)."""
    return sorted(state.of_kind(HiddenFile), key=lambda h: (h.path, h.site, h.sha256))


def unhide(store: Store, hidden: HiddenFile | HiddenFolder, expected: str) -> Applied | Rejected:
    """Blendet Datei oder Ordner wieder ein; `expected`: Prüfsumme der angezeigten Fassung."""
    return store.apply([Delete(hidden.address, expected=expected)])


def missing_file_findings(incoming: Incoming, user: str) -> list[Finding]:
    """Fehler je Dokument von `user`, dessen Datei am Ablageort fehlt: weder unter seinem Pfad
    mit gleichem Inhalt noch unter einem anderen Pfad desselben Ablageorts (ADR 0003; dann führt
    `relocate_documents` beim Start den Pfad nach, ohne Befund)."""
    return [
        Finding(MISSING_FILE, Severity.ERROR, d.address, f"Datei fehlt: {d.site}/{d.path}")
        for d in incoming.missing_documents(user)
    ]


def relocate_documents(store: Store) -> list[str]:
    """Start: führt den Pfad jedes Dokuments nach, dessen Datei nicht mehr unter ihrem Pfad liegt,
    aber mit gleichem SHA-256 an anderer Stelle desselben Ablageorts (ADR 0003); je Änderung eine
    Zeile."""
    state = store.state()
    lines: list[str] = []
    for d, new_path in Incoming(all_site_files(store), state, "").moved_documents():
        moved = d.model_copy(update={"path": new_path})
        if isinstance(store.apply([Put(moved, entry_checksum(d))]), Applied):
            lines.append(f"{d.site}: {d.path} -> {new_path}")
    return lines
