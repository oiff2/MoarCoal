"""Der Datei-Explorer von Windows aus dem Server in WSL: der einzige Ort, der ihn startet.

Der Server läuft in WSL, der Browser unter Windows (ADR 0002); ein `file://`-Link von einer
http-Seite sperrt der Browser, also öffnet der Server den Explorer selbst. Beide Aufrufe haben eine
feste Argumentliste, laufen ohne Shell, und nichts davon kommt aus der Anfrage: der Pfad stammt aus
dem Stand des Servers. Aufgerufen wird nur auf Klick (POST der Belege-Seite)."""

import subprocess
from pathlib import Path
from typing import Protocol

WSLPATH_TIMEOUT_SECONDS = 5

NOT_AVAILABLE = (
    "Der Datei-Explorer lässt sich nicht öffnen: das geht nur mit Windows und WSL "
    "(`wslpath` und `explorer.exe` müssen erreichbar sein)."
)


class FolderOpener(Protocol):
    def reveal(self, file: Path) -> str | None:
        """Den Ordner der Datei im Datei-Explorer öffnen, die Datei markiert; `None`, wenn der
        Aufruf gestartet ist, sonst die Meldung für die Seite."""
        ...


def wslpath_command(path: Path) -> list[str]:
    """Feste Argumentliste der Umwandlung in einen Windows-Pfad (ein Test prüft sie wörtlich)."""
    return ["wslpath", "-w", str(path)]


def explorer_command(windows_path: str) -> list[str]:
    """Feste Argumentliste des Explorer-Aufrufs mit markierter Datei (ein Test prüft sie)."""
    return ["explorer.exe", f"/select,{windows_path}"]


class ExplorerOpener:
    """Der echte Baustein; Tests setzen einen eigenen ein, damit kein Prozess startet."""

    def reveal(self, file: Path) -> str | None:
        try:
            converted = subprocess.run(
                wslpath_command(file),
                capture_output=True,
                text=True,
                check=True,
                timeout=WSLPATH_TIMEOUT_SECONDS,
            )
            windows_path = converted.stdout.strip()
            if not windows_path:
                return NOT_AVAILABLE
            # Kein Warten: explorer.exe endet von selbst, sein Rückgabewert sagt nichts.
            subprocess.Popen(
                explorer_command(windows_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return NOT_AVAILABLE
        return None
