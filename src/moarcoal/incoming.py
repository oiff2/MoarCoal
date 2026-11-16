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


def all_site_files(store: Store) -> list[SiteFile]:
    """Alle Dateien aller Ablageorte."""
    return [file for site in store.site_names() for file in store.list_site_files(site)]


def incoming_files(files: Sequence[SiteFile], state: State, user: str) -> list[SiteFile]:
    """Der Eingang von `user`: nicht von ihm aufgenommen, nicht ausgeblendet.

    Gleicher Inhalt an mehreren Stellen erscheint einmal, mit dem ersten Pfad.
    """
    known = {d.sha256 for d in state.of_kind(Document) if d.owner == user}
    known |= {h.sha256 for h in state.of_kind(HiddenFile)}
    folders = state.of_kind(HiddenFolder)
    shown: dict[str, SiteFile] = {}
    for file in files:
        if file.sha256 not in known and not in_hidden_folder(file, folders):
            shown.setdefault(file.sha256, file)
    return list(shown.values())


def in_hidden_folder(file: SiteFile, folders: Sequence[HiddenFolder]) -> bool:
    """Liegt die Datei unter einem ausgeblendeten Ordner ihres Ablageorts (beliebig tief)?"""
    return any(f.site == file.site and file.path.startswith(f.path + "/") for f in folders)


def folder_path_error(files: Sequence[SiteFile], site: str, path: str) -> str | None:
    """Warum `path` kein Ordner von `site` ist, den man ausblenden kann; `None`, wenn er einer ist.

    Es gelten die Pfadregeln von `Store.read_site_file` (relativ, ohne `..`). Als Ordner gilt, was
    mindestens eine aufgelistete Datei enthält; aufgelistet ist nur, was im Ablageort liegt.
    """
    parts = path.split("/")
    if not path or path.startswith("/") or ".." in parts or "" in parts:
        return "Der Pfad muss relativ zum Ablageort sein, ohne „..“."
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
