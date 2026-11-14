"""Start, Stopp und Neustart (#116): Wahl der Aktion, Portprüfung, PID-Datei, Browser.

Kein echter Browser, kein Beenden echter Prozesse, kein Schlafen: Prozesszugriff, Uhr und
Browser sind eingesetzt.
"""

import asyncio
import os
import socket
from pathlib import Path

import pytest
import uvicorn

from moarcoal import __main__ as cli
from moarcoal.instance import (
    Action,
    Holder,
    Situation,
    bind_port,
    choose_action,
    classify,
    wait_for_port,
)
from moarcoal.storage import read_pid, remove_pid, write_pid

FOREIGN = Holder(4242, "other")


@pytest.mark.parametrize(
    ("command", "situation", "force", "expected"),
    [
        ("start", Situation.FREE, False, Action.START),
        ("start", Situation.OWN, False, Action.START),  # der Bindetest meldet „nicht frei“
        ("start", Situation.FOREIGN, False, Action.START),
        ("stop", Situation.FREE, False, Action.NOT_RUNNING),
        ("stop", Situation.FOREIGN, False, Action.NOT_RUNNING),
        ("stop", Situation.OWN, False, Action.STOP_OWN),
        ("restart", Situation.FREE, False, Action.START),
        ("restart", Situation.FREE, True, Action.START),
        ("restart", Situation.OWN, False, Action.STOP_OWN_THEN_START),
        ("restart", Situation.OWN, True, Action.STOP_OWN_THEN_START),
        ("restart", Situation.FOREIGN, False, Action.REFUSE_FOREIGN),
        ("restart", Situation.FOREIGN, True, Action.FORCE_THEN_START),
    ],
)
def test_choose_action(command: cli.Command, situation: Situation, force: bool, expected: Action):
    assert choose_action(command, situation, force) is expected


def test_classify_needs_listener_with_recorded_pid() -> None:
    assert classify(None, 4242) is Situation.FREE
    assert classify(FOREIGN, 4242) is Situation.OWN
    assert classify(FOREIGN, 1) is Situation.FOREIGN  # veraltete Datei: PID gehört nicht dazu
    assert classify(FOREIGN, None) is Situation.FOREIGN


def test_bind_port_returns_socket_or_error() -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        taken = bind_port(blocker.getsockname()[1])
    assert isinstance(taken, OSError)
    free = bind_port(0)
    assert isinstance(free, socket.socket)
    free.close()


def test_wait_for_port_polls_until_free_or_timeout() -> None:
    now = [0.0]
    calls: list[int] = []
    sock = socket.socket()

    def bind(port: int) -> socket.socket | OSError:
        calls.append(port)
        return sock if len(calls) == 3 else OSError("busy")

    def sleep(seconds: float) -> None:
        now[0] += seconds

    assert wait_for_port(7, 10, bind, sleep, lambda: now[0]) is sock
    assert calls == [7, 7, 7]
    sock.close()

    calls.clear()
    now[0] = 0.0
    failed = wait_for_port(7, 1, lambda _p: OSError("busy"), sleep, lambda: now[0])
    assert isinstance(failed, OSError)
    assert now[0] >= 1


def test_pid_file_roundtrip_and_stale_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    assert read_pid(data) is None
    write_pid(data, 111)
    write_pid(data, 222)  # überschreibt die veraltete Datei
    assert read_pid(data) == 222
    remove_pid(data, 111)  # fremde PID: bleibt
    assert read_pid(data) == 222
    remove_pid(data, 222)
    assert read_pid(data) is None
    (data / "moarcoal.pid").write_text("kaputt", encoding="utf-8")
    assert read_pid(data) is None


class Recorder:
    def __init__(self, holder: Holder | None, stop_results: list[bool]) -> None:
        self.holder = holder
        self.stop_results = stop_results
        self.stops: list[tuple[int, bool]] = []
        self.starts: list[tuple[bool, bool]] = []


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(None, [True])

    def holder(port: int) -> Holder | None:
        return recorder.holder

    monkeypatch.setattr(cli, "port_holder", holder)

    def stop(pid: int, timeout: float, kill: bool = False) -> bool:
        recorder.stops.append((pid, kill))
        return recorder.stop_results.pop(0)

    def start(port: int, data_dir: Path, open_browser: bool, wait: bool = False) -> None:
        recorder.starts.append((open_browser, wait))

    monkeypatch.setattr(cli, "stop_process", stop)
    monkeypatch.setattr(cli, "start", start)
    return recorder


def test_restart_stops_own_instance_then_starts_with_browser(rec: Recorder, tmp_path: Path):
    rec.holder = FOREIGN
    write_pid(tmp_path, FOREIGN.pid)
    cli.handle("restart", False, 1, tmp_path)
    assert rec.stops == [(4242, False)]
    assert rec.starts == [(True, True)]


def test_restart_without_instance_just_starts(rec: Recorder, tmp_path: Path) -> None:
    cli.handle("restart", False, 1, tmp_path)
    assert rec.stops == []
    assert rec.starts == [(True, False)]


def test_restart_with_stale_pid_file_ignores_it(rec: Recorder, tmp_path: Path) -> None:
    write_pid(tmp_path, 999)
    cli.handle("restart", False, 1, tmp_path)
    assert rec.stops == [] and rec.starts == [(True, False)]


def test_restart_refuses_foreign_process(
    rec: Recorder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rec.holder = FOREIGN
    with pytest.raises(SystemExit) as exit_info:
        cli.handle("restart", False, 1, tmp_path)
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "other" in err and "4242" in err and "--force" in err and "MOARCOAL_PORT" in err
    assert rec.stops == [] and rec.starts == []


def test_force_names_process_and_escalates_to_kill(
    rec: Recorder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rec.holder = FOREIGN
    rec.stop_results = [False, True]  # SIGTERM reicht nicht, SIGKILL schon
    cli.handle("restart", True, 1, tmp_path)
    assert "other (PID 4242)" in capsys.readouterr().out
    assert rec.stops == [(4242, False), (4242, True)]
    assert rec.starts == [(True, True)]


def test_force_aborts_when_process_cannot_be_stopped(
    rec: Recorder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rec.holder = FOREIGN
    rec.stop_results = [False, False]
    with pytest.raises(SystemExit) as exit_info:
        cli.handle("restart", True, 1, tmp_path)
    assert exit_info.value.code == 1
    assert "4242" in capsys.readouterr().err
    assert rec.starts == []


def test_restart_of_own_instance_never_kills(rec: Recorder, tmp_path: Path) -> None:
    rec.holder = FOREIGN
    write_pid(tmp_path, FOREIGN.pid)
    rec.stop_results = [False]
    with pytest.raises(SystemExit):
        cli.handle("restart", False, 1, tmp_path)
    assert rec.stops == [(4242, False)]


def test_stop_without_instance_says_so_and_exits_normally(
    rec: Recorder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.handle("stop", False, 1, tmp_path)
    assert "läuft nicht" in capsys.readouterr().out
    assert rec.stops == [] and rec.starts == []


def test_stop_ends_own_instance_only(rec: Recorder, tmp_path: Path) -> None:
    rec.holder = FOREIGN
    cli.handle("stop", False, 1, tmp_path)  # keine PID-Datei: fremd
    assert rec.stops == []
    write_pid(tmp_path, FOREIGN.pid)
    cli.handle("stop", False, 1, tmp_path)
    assert rec.stops == [(4242, False)] and rec.starts == []


def test_start_opens_browser_and_plain_call_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[bool] = []

    def no_holder(port: int) -> None:
        return None

    monkeypatch.setattr(cli, "port_holder", no_holder)

    def run_server(port: int, data_dir: Path, sock: socket.socket, open_browser: bool) -> None:
        sock.close()
        seen.append(open_browser)

    monkeypatch.setattr(cli, "run_server", run_server)
    monkeypatch.setattr(cli, "read_port", lambda: 0)
    monkeypatch.setattr(cli, "read_data_dir", lambda: tmp_path)
    cli.main(["start"])
    cli.main([])
    assert seen == [True, False]


def test_browser_opens_only_after_server_started(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(cli.webbrowser, "open", fake_open)
    started = [False]

    async def fake_startup(
        self: uvicorn.Server, sockets: list[socket.socket] | None = None
    ) -> None:
        self.started = started[0]

    monkeypatch.setattr(uvicorn.Server, "startup", fake_startup)
    server = cli.BrowserServer(uvicorn.Config(lambda *_a: None))
    server.open_url = "http://127.0.0.1:1/"
    asyncio.run(server.startup())
    assert opened == []
    started[0] = True
    asyncio.run(server.startup())
    assert opened == ["http://127.0.0.1:1/"]
    server.open_url = None
    asyncio.run(server.startup())
    assert opened == ["http://127.0.0.1:1/"]


def test_server_writes_and_removes_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    during: list[int | None] = []

    def fake_run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        during.append(read_pid(tmp_path))

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    sock = bind_port(0)
    assert isinstance(sock, socket.socket)
    cli.run_server(sock.getsockname()[1], tmp_path, sock, open_browser=False)
    assert during == [os.getpid()]
    assert read_pid(tmp_path) is None
    assert "http://127.0.0.1:" in capsys.readouterr().out
