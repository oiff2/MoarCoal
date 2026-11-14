"""Startpunkt: `uv run moarcoal [start | stop | restart [--force]]`, Server an 127.0.0.1."""

import argparse
import os
import socket
import sys
import webbrowser
from collections.abc import Mapping, Sequence
from pathlib import Path

import uvicorn

from moarcoal.app import create_app
from moarcoal.instance import (
    HOST,
    Action,
    Command,
    Holder,
    bind_port,
    choose_action,
    classify,
    port_holder,
    stop_process,
    wait_for_port,
)
from moarcoal.storage import default_data_dir, read_pid, remove_pid, write_pid

DEFAULT_PORT = 8765
PORT_ENV = "MOARCOAL_PORT"
DATA_DIR_ENV = "MOARCOAL_DATA_DIR"
STOP_WAIT_SECONDS = 10.0


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


class BrowserServer(uvicorn.Server):
    """Öffnet `open_url` im Browser, sobald der Server angelaufen ist (Zustand `started`)."""

    open_url: str | None = None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if self.started and self.open_url:
            webbrowser.open(self.open_url)


def run_server(port: int, data_dir: Path, sock: socket.socket, open_browser: bool) -> None:
    url = f"http://{HOST}:{port}/"
    print(f"MoarCoal läuft unter {url}")
    server = BrowserServer(uvicorn.Config(create_app(port, data_dir), log_level="info"))
    server.open_url = url if open_browser else None
    pid = os.getpid()
    write_pid(data_dir, pid)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        remove_pid(data_dir, pid)


def fail(message: str) -> SystemExit:
    print(message, file=sys.stderr)
    return SystemExit(1)


def start(port: int, data_dir: Path, open_browser: bool, wait: bool = False) -> None:
    result = wait_for_port(port, STOP_WAIT_SECONDS) if wait else bind_port(port)
    if isinstance(result, OSError):
        if wait:
            raise fail(
                f"Port {port} auf {HOST} wurde in {STOP_WAIT_SECONDS:.0f} Sekunden nicht frei."
            )
        raise fail(
            f"Port {port} auf {HOST} ist nicht frei ({result.strerror}). "
            f"MoarCoal läuft vielleicht schon; sonst Port über {PORT_ENV} ändern."
        )
    run_server(port, data_dir, result, open_browser)


def describe(holder: Holder) -> str:
    return f"{holder.name} (PID {holder.pid})"


def free_port(holder: Holder, escalate: bool) -> None:
    """Beendet den Halter des Ports (mit `escalate` nach SIGTERM noch per SIGKILL); scheitert
    das, bricht der Befehl mit Meldung ab."""
    if stop_process(holder.pid, STOP_WAIT_SECONDS):
        return
    if not (escalate and stop_process(holder.pid, STOP_WAIT_SECONDS, kill=True)):
        raise fail(f"{describe(holder)} lässt sich nicht beenden.")


def handle(command: Command, force: bool, port: int, data_dir: Path) -> None:
    holder = port_holder(port)
    action = choose_action(command, classify(holder, read_pid(data_dir)), force)
    if action is Action.START:
        start(port, data_dir, open_browser=command != "stop")
    elif action is Action.NOT_RUNNING:
        print("MoarCoal läuft nicht.")
    elif holder is None:  # nur für den Typchecker: die übrigen Aktionen setzen einen Halter voraus
        raise AssertionError(action)
    elif action is Action.STOP_OWN:
        free_port(holder, escalate=False)
        print("MoarCoal beendet.")
    elif action is Action.REFUSE_FOREIGN:
        raise fail(
            f"Port {port} gehört {describe(holder)}, nicht MoarCoal; es wird nichts beendet. "
            f"`moarcoal restart --force` beendet den Prozess, oder Port über {PORT_ENV} ändern."
        )
    else:
        forced = action is Action.FORCE_THEN_START
        if forced:
            print(f"Beende {describe(holder)}, der Port {port} belegt.")
        free_port(holder, escalate=forced)
        start(port, data_dir, open_browser=True, wait=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="moarcoal")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("start", help="Server starten und die Startseite im Browser öffnen")
    commands.add_parser("stop", help="eigene laufende Instanz beenden")
    restart = commands.add_parser("restart", help="eigene Instanz beenden und neu starten")
    restart.add_argument("--force", action="store_true", help="auch einen fremden Prozess beenden")
    args = parser.parse_args(argv)
    port, data_dir = read_port(), read_data_dir()
    if args.command is None:
        start(port, data_dir, open_browser=False)
    else:
        handle(args.command, getattr(args, "force", False), port, data_dir)


if __name__ == "__main__":
    main()
