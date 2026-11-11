"""Tests der Absicherung (ADR 0007) und der Startseite, über den Test-Client."""

import httpx
import pytest
from fastapi.testclient import TestClient

from moarcoal.__main__ import DEFAULT_PORT, read_port
from moarcoal.app import create_app

PORT = 4711


def client(host: str = "127.0.0.1") -> httpx.Client:
    return TestClient(create_app(PORT), base_url=f"http://{host}:{PORT}")


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
