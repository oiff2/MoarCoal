"""Tests der Absicherung (ADR 0007) und der Startseite, über den Test-Client."""

import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from moarcoal.__main__ import DEFAULT_PORT, main, read_data_dir, read_port
from moarcoal.app import create_app
from moarcoal.storage import default_data_dir

PORT = 4711
DATA_DIR: list[Path] = []  # Wegwerfverzeichnis des laufenden Tests, nie das echte


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    DATA_DIR.append(tmp_path)
    yield
    DATA_DIR.clear()


def client(host: str = "127.0.0.1") -> httpx.Client:
    return TestClient(create_app(PORT, DATA_DIR[0]), base_url=f"http://{host}:{PORT}")


def test_start_page_ok_and_loads_local_htmx() -> None:
    response = client().get("/")
    assert response.status_code == 200
    assert 'src="/static/htmx.min.js"' in response.text
    assert "http://" not in response.text and "https://" not in response.text
    assert client().get("/static/htmx.min.js").status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_own_hosts_accepted(host: str) -> None:
    assert client(host).get("/").status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example"])
def test_foreign_host_rejected(host: str) -> None:
    assert client(host).get("/").status_code == 400


def test_host_with_wrong_port_rejected() -> None:
    response = client().get("/", headers={"Host": "127.0.0.1:9999"})
    assert response.status_code == 400


def test_missing_host_rejected() -> None:
    response = client().get("/", headers={"Host": ""})
    assert response.status_code == 400


def test_post_with_foreign_origin_rejected() -> None:
    response = client().post("/", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403


def test_post_with_foreign_origin_rejected_even_if_port_matches() -> None:
    response = client().post("/", headers={"Origin": f"http://evil.example:{PORT}"})
    assert response.status_code == 403


def test_post_without_origin_and_fetch_site_rejected() -> None:
    assert client().post("/").status_code == 403


@pytest.mark.parametrize("origin", [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"])
def test_post_with_own_origin_passes_protection(origin: str) -> None:
    # Die Startseite nimmt kein POST an: 405 heißt, die Absicherung hat durchgelassen.
    assert client().post("/", headers={"Origin": origin}).status_code == 405


def test_post_with_same_origin_fetch_site_passes_protection() -> None:
    response = client().post("/", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 405


def test_post_with_cross_site_fetch_site_rejected() -> None:
    assert client().post("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_changing_methods_need_origin(method: str) -> None:
    assert client().request(method, "/").status_code == 403


def test_head_needs_no_origin() -> None:
    # 405: FastAPI beantwortet HEAD auf GET-Routen nicht; die Absicherung hat durchgelassen.
    assert client().head("/").status_code == 405


@pytest.mark.parametrize(
    ("method", "path", "headers"),
    [
        ("GET", "/", {}),
        ("GET", "/static/htmx.min.js", {}),
        ("GET", "/gibt-es-nicht", {}),
        ("GET", "/", {"Host": "evil.example"}),
        ("POST", "/", {}),
    ],
)
def test_every_response_has_security_headers(
    method: str, path: str, headers: dict[str, str]
) -> None:
    response = client().request(method, path, headers=headers)
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_no_cors_headers() -> None:
    response = client().get("/", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_start_page_has_no_inline_script() -> None:
    html = client().get("/").text.lower()
    assert "<script>" not in html
    assert "onclick" not in html


def test_port_default_and_override() -> None:
    assert read_port({}) == DEFAULT_PORT == 8765
    assert read_port({"MOARCOAL_PORT": "9001"}) == 9001


@pytest.mark.parametrize("value", ["abc", "0", "70000"])
def test_invalid_port_exits_with_message(value: str) -> None:
    with pytest.raises(SystemExit, match="MOARCOAL_PORT"):
        read_port({"MOARCOAL_PORT": value})


def test_data_dir_default_and_override() -> None:
    assert read_data_dir({}) == default_data_dir() == Path.home() / "MoarCoal"
    assert read_data_dir({"MOARCOAL_DATA_DIR": "/tmp/anderswo"}) == Path("/tmp/anderswo")
    assert read_data_dir({"MOARCOAL_DATA_DIR": ""}) == default_data_dir()


def test_start_page_links_registered_modules() -> None:
    assert 'href="/arbeit"' in client().get("/").text


def test_main_aborts_when_port_taken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        monkeypatch.setenv("MOARCOAL_PORT", str(port))
        monkeypatch.setenv("MOARCOAL_DATA_DIR", str(tmp_path))
        with pytest.raises(SystemExit) as exit_info:
            main([])
    assert exit_info.value.code not in (0, None)
    err = capsys.readouterr().err
    assert f"Port {port}" in err and "nicht frei" in err and "MOARCOAL_PORT" in err


@pytest.mark.skipif(
    sys.platform == "win32", reason="SO_REUSEADDR hat unter Windows andere Bedeutung"
)
def test_main_binds_port_in_time_wait(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as old_server:
        old_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        old_server.bind(("127.0.0.1", 0))
        old_server.listen()
        port = old_server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client_sock:
            accepted, _ = old_server.accept()
            accepted.close()  # der Server schließt zuerst: TIME-WAIT auf dem Server-Port
            client_sock.recv(1)
    bound: list[int] = []

    def fake_run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        assert sockets
        bound.append(sockets[0].getsockname()[1])

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    monkeypatch.setenv("MOARCOAL_PORT", str(port))
    monkeypatch.setenv("MOARCOAL_DATA_DIR", str(tmp_path))
    main([])
    assert bound == [port]
