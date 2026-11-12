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
