"""PID-Datei im Datenverzeichnis: wer gerade den Server dieses Verzeichnisses führt."""

from pathlib import Path

PID_FILE_NAME = "moarcoal.pid"


def read_pid(data_dir: Path) -> int | None:
    """PID aus der Datei; fehlt sie oder ist sie unlesbar, gibt es keine."""
    try:
        return int((data_dir / PID_FILE_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(data_dir: Path, pid: int) -> None:
    """Schreibt die PID und überschreibt dabei eine veraltete Datei."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / PID_FILE_NAME).write_text(f"{pid}\n", encoding="utf-8")


def remove_pid(data_dir: Path, pid: int) -> None:
    """Löscht die Datei, aber nur wenn sie noch `pid` trägt (nie die einer neueren Instanz)."""
    if read_pid(data_dir) == pid:
        (data_dir / PID_FILE_NAME).unlink(missing_ok=True)
