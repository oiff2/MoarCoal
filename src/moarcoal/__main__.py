"""Startpunkt: `uv run moarcoal` startet den Server an 127.0.0.1."""

import os
import socket
import sys
from collections.abc import Mapping
from pathlib import Path

import uvicorn

from moarcoal.app import create_app
from moarcoal.storage import default_data_dir

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_ENV = "MOARCOAL_PORT"
DATA_DIR_ENV = "MOARCOAL_DATA_DIR"


def read_port(env: Mapping[str, str] = os.environ) -> int:
    raw = env.get(PORT_ENV)
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise SystemExit(f"{PORT_ENV}={raw!r} ist kein gültiger Port (1 bis 65535).")
    return port


def read_data_dir(env: Mapping[str, str] = os.environ) -> Path:
    """Datenverzeichnis: `MOARCOAL_DATA_DIR` oder `~/MoarCoal`."""
    raw = env.get(DATA_DIR_ENV)
    return Path(raw) if raw else default_data_dir()


def main() -> None:
    port = read_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # unter Windows erlaubt die Option doppeltes Binden
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
    except OSError as error:
        sock.close()
        print(
            f"Port {port} auf {HOST} ist nicht frei ({error.strerror}). "
            f"MoarCoal läuft vielleicht schon; sonst Port über {PORT_ENV} ändern.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    server = uvicorn.Server(uvicorn.Config(create_app(port, read_data_dir()), log_level="info"))
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
