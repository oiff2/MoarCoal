"""Startpunkt: `uv run moarcoal` startet den Server an 127.0.0.1."""

import os
import socket
import sys
from collections.abc import Mapping

import uvicorn

from moarcoal.app import create_app

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_ENV = "MOARCOAL_PORT"


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


def main() -> None:
    port = read_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    server = uvicorn.Server(uvicorn.Config(create_app(port), log_level="info"))
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
