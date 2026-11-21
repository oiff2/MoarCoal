"""Ablageorte: benannte Ordner, aus denen MoarCoal Dateien liest, nie schreibt (Spec 3.6).

`Sites` listet und liest; welche Ablageorte es gibt, lädt `Store` aus `common/sites.json`. Für
Pfade gilt eine Regel (`path_error`): relativ, in Normalform, ohne `..`.
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_SITE_FILE_BYTES = 50_000_000
PATH_RULE = "Der Pfad muss relativ zum Ablageort sein, ohne „..“."


class SiteFileError(Exception):
    """Eine Datei an einem Ablageort lässt sich nicht lesen; die Meldung ist für den Nutzer."""


@dataclass(frozen=True)
class SiteFile:
    """Eine Datei an einem Ablageort: Ablageort, Pfad relativ dazu (mit `/`), Größe, SHA-256."""

    site: str
    path: str
    size: int
    sha256: str


def path_error(path: str) -> str | None:
    """Warum `path` kein Pfad relativ zu einem Ordner ist; `None`, wenn er einer ist.

    Gilt nur die Normalform: nicht leer, nicht absolut, kein `..`, kein `.`-Teil, kein doppelter
    und kein abschließender Schrägstrich.
    """
    pure = PurePosixPath(path)
    if str(pure) != path or not pure.parts or pure.is_absolute() or ".." in pure.parts:
        return PATH_RULE
    return None


class Sites:
    """Die Ablageorte (Name -> Ordner); es wird nur gelesen. Die SHA-256 der gelisteten Dateien
    werden zwischengespeichert, solange Größe und Änderungszeit gleich bleiben."""

    def __init__(self, folders: Mapping[str, Path]) -> None:
        self._folders = dict(folders)
        self._hashes: dict[tuple[str, int, int], str] = {}  # (Datei, Größe, mtime) -> SHA-256

    def names(self) -> list[str]:
        return sorted(self._folders)

    def _folder(self, site: str) -> Path:
        folder = self._folders.get(site)
        if folder is None:
            raise SiteFileError(f"Unbekannter Ablageort {site!r}.")
        return folder

    def has_file(self, site: str, path: str) -> bool:
        """Ob am Ablageort unter `path` eine Datei liegt (ohne sie zu lesen); unbekannter
        Ablageort oder ungültiger Pfad: nein."""
        folder = self._folders.get(site)
        if folder is None or path_error(path) is not None:
            return False
        target = (folder / path).resolve()
        return target.is_relative_to(folder.resolve()) and target.is_file()

    def read(self, site: str, path: str) -> bytes:
        """Inhalt einer Datei an einem Ablageort."""
        folder = self._folder(site)
        if (error := path_error(path)) is not None:
            raise SiteFileError(error)
        target = (folder / path).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise SiteFileError("Der Pfad führt aus dem Ablageort hinaus.")
        try:
            if target.stat().st_size > MAX_SITE_FILE_BYTES:
                raise SiteFileError("Die Datei ist zu groß.")
            return target.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as error:
            raise SiteFileError(f"Am Ablageort {site!r} gibt es keine Datei {path!r}.") from error
        except OSError as error:
            raise SiteFileError(f"Die Datei lässt sich nicht lesen ({error.strerror}).") from error

    def files(self, site: str) -> list[SiteFile]:
        """Alle Dateien eines Ablageorts, rekursiv und nach Pfad sortiert.

        Es gelten die Regeln von `read`: Verzeichnis-Links werden nicht verfolgt, Dateien mit Ziel
        außerhalb des Ablageorts, zu große und unlesbare Dateien fehlen in der Liste. Ordner mit
        Punkt am Anfang (etwa `.git`) werden samt Inhalt übergangen.
        """
        base = self._folder(site).resolve()
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
                    sha256 = self._hashes.get(key)
                    if sha256 is None:
                        sha256 = self._hashes[key] = hashlib.sha256(target.read_bytes()).hexdigest()
                except OSError:
                    continue
                relative = file.relative_to(base).as_posix()
                found.append(SiteFile(site, relative, info.st_size, sha256))
        return sorted(found, key=lambda f: f.path)
