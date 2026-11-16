"""Der Eingang: Dateien der Ablageorte, die weder aufgenommen noch ausgeblendet sind (Spec 3.6).

Erkannt wird eine Datei am SHA-256; eine umbenannte, schon aufgenommene Datei ist nicht neu.
Aufgenommen wird nur über `take_in` (`documents.py`); hier steht das Auflisten und Ausblenden.
"""

from collections.abc import Sequence

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
)
from moarcoal.storage.sites import path_error


def all_site_files(store: Store) -> list[SiteFile]:
    """Alle Dateien aller Ablageorte."""
    return [file for site in store.sites.names() for file in store.sites.files(site)]


def site_files_of(
    files: Sequence[SiteFile], state: State, user: str
) -> list[tuple[SiteFile, Document | None]]:
    """Die Dateien der Ablage von `user`, eine je Inhalt (mit dem ersten Pfad), ohne Ausgeblendete;
    zu jeder ihr Dokument, wenn `user` sie aufgenommen hat.

    Hat `user` den Inhalt aufgenommen, steht er mit seinem Dokument da, auch wenn ihn jemand
    ausgeblendet hat; so hat jede Datei genau eine Stelle (Ablage oder Ausgeblendet).
    """
    documents: dict[str, Document] = {}
    for document in state.of_kind(Document):
        if document.owner == user:
            documents.setdefault(document.sha256, document)
    hidden = {h.sha256 for h in state.of_kind(HiddenFile)}
    folders = state.of_kind(HiddenFolder)
    shown: dict[str, tuple[SiteFile, Document | None]] = {}
    for file in files:
        if file.sha256 in documents or (
            file.sha256 not in hidden and not in_hidden_folder(file, folders)
        ):
            shown.setdefault(file.sha256, (file, documents.get(file.sha256)))
    return list(shown.values())


def incoming_files(files: Sequence[SiteFile], state: State, user: str) -> list[SiteFile]:
    """Der Eingang von `user`: die Dateien seiner Ablage, die er nicht aufgenommen hat."""
    return [file for file, document in site_files_of(files, state, user) if document is None]


def in_hidden_folder(file: SiteFile, folders: Sequence[HiddenFolder]) -> bool:
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
