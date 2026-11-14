"""Eigene Instanz erkennen, beenden und den Port freimachen (`moarcoal stop`, `restart`).

`choose_action` ist rein; alles mit Prozessen, Port und Uhr steht darunter und lässt sich
einsetzen, damit die Tests nie einen echten Prozess anfassen.
"""

import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal

import psutil

HOST = "127.0.0.1"
FREE_WAIT_SECONDS = 10.0
POLL_SECONDS = 0.1

Command = Literal["start", "stop", "restart"]


@dataclass(frozen=True)
class Holder:
    """Der Prozess, der auf dem Port lauscht."""

    pid: int
    name: str


class Situation(Enum):
    FREE = auto()
    OWN = auto()
    FOREIGN = auto()


class Action(Enum):
    START = auto()
    NOT_RUNNING = auto()
    STOP_OWN = auto()
    STOP_OWN_THEN_START = auto()
    REFUSE_FOREIGN = auto()
    FORCE_THEN_START = auto()


def choose_action(command: Command, situation: Situation, force: bool = False) -> Action:
    """Welche Aktion `command` in `situation` auslöst. Belegt der Port bei `start`, meldet das
    der Bindetest; `stop` beendet nur die eigene Instanz."""
    if command == "start":
        return Action.START
    if command == "stop":
        return Action.STOP_OWN if situation is Situation.OWN else Action.NOT_RUNNING
    if situation is Situation.FREE:
        return Action.START
    if situation is Situation.OWN:
        return Action.STOP_OWN_THEN_START
    return Action.FORCE_THEN_START if force else Action.REFUSE_FOREIGN


def classify(holder: Holder | None, recorded_pid: int | None) -> Situation:
    """Eigen ist nur der Prozess, der auf dem Port lauscht und dessen PID in der Datei steht;
    eine veraltete PID-Datei (Absturz) zählt nicht."""
    if holder is None:
        return Situation.FREE
    return Situation.OWN if holder.pid == recorded_pid else Situation.FOREIGN


def bind_port(port: int) -> socket.socket | OSError:
    """Bindetest: der gebundene Socket, falls der Port frei ist, sonst der Fehler."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # unter Windows erlaubt die Option doppeltes Binden
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
    except OSError as error:
        sock.close()
        return error
    return sock


def wait_for_port(
    port: int,
    timeout: float = FREE_WAIT_SECONDS,
    bind: Callable[[int], socket.socket | OSError] = bind_port,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> socket.socket | OSError:
    """Bindet den Port, sobald er frei ist; nach `timeout` Sekunden der letzte Fehler."""
    deadline = clock() + timeout
    result = bind(port)
    while isinstance(result, OSError) and clock() < deadline:
        sleep(POLL_SECONDS)
        result = bind(port)
    return result


def port_holder(port: int) -> Holder | None:
    """Prozess, der auf `port` lauscht; ohne Rechte, ihn zu sehen, `None`."""
    try:
        connections = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        return None
    for connection in connections:
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port == port
            and connection.pid is not None
        ):
            try:
                return Holder(connection.pid, psutil.Process(connection.pid).name())
            except psutil.NoSuchProcess:
                return None
    return None


def stop_process(pid: int, timeout: float, kill: bool = False) -> bool:
    """Beendet `pid` (SIGTERM, mit `kill` SIGKILL) und wartet auf sein Ende. `False`, wenn er
    nicht beendbar ist (fremder Nutzer) oder nach `timeout` noch läuft."""
    try:
        process = psutil.Process(pid)
        process.kill() if kill else process.terminate()
        process.wait(timeout)
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, psutil.TimeoutExpired):
        return False
    return True
