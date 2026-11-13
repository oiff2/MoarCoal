"""Baustein Ausblendung im Eingang: eine Datei erscheint für alle Nutzer nicht mehr im Eingang."""

from pydantic import Field

from moarcoal.storage.documents import SHA256_PATTERN
from moarcoal.storage.entries import Entry, entry_kind

HIDDEN_FILE_SCHEMA = "datenebene/1"
COMMON_OWNER = "common"  # gemeinsame Einträge gehören keinem Nutzer


class HiddenFile(Entry):
    """Eine im Eingang ausgeblendete Datei, erkannt am SHA-256 (nicht am Pfad).

    Ablageort und Pfad stehen nur zur Anzeige; die Notiz ist freiwillig. Sie gilt für alle Nutzer,
    der Eigentümer ist immer `COMMON_OWNER`.
    """

    sha256: str = Field(pattern=SHA256_PATTERN)
    site: str = Field(min_length=1)
    path: str = Field(min_length=1)
    note: str = ""


def hidden_file_path(entry: HiddenFile) -> str:
    return "common/hidden_files.json"


HIDDEN_FILE_KIND = entry_kind(HiddenFile, HIDDEN_FILE_SCHEMA, hidden_file_path)


class HiddenFolder(Entry):
    """Ein im Eingang ausgeblendeter Ordner eines Ablageorts, erkannt an Ablageort und Pfad.

    Er nimmt alles darunter mit, auch spätere Dateien. Der Pfad ist relativ zum Ablageort, mit `/`,
    ohne `..`. Er gilt für alle Nutzer, der Eigentümer ist immer `COMMON_OWNER`.
    """

    site: str = Field(min_length=1)
    path: str = Field(min_length=1)


def hidden_folder_path(entry: HiddenFolder) -> str:
    return "common/hidden_folders.json"


HIDDEN_FOLDER_KIND = entry_kind(HiddenFolder, HIDDEN_FILE_SCHEMA, hidden_folder_path)
