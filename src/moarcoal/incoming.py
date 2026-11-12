"""Der Eingang: Dateien der Ablageorte, die weder aufgenommen noch ausgeblendet sind (Spec 3.6).

Erkannt wird eine Datei am SHA-256; eine umbenannte, schon aufgenommene Datei ist nicht neu.
Aufgenommen wird nur über `take_in` (`documents.py`); hier steht das Auflisten und Ausblenden.
"""

from collections.abc import Sequence

from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
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
