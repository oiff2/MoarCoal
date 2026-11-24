"""Tests: Ordner einer Datei im Datei-Explorer öffnen (#267; nur tmp_path, kein Prozessstart)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient
from test_belege import FIXTURE, ORIGIN, PORT, SHA, main_of

from moarcoal.web import explorer
from moarcoal.web.explorer import ExplorerOpener, explorer_command, wslpath_command
from moarcoal.web.links import open_folder_url


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    (folder / "2025" / "protokoll.html").write_bytes(FIXTURE.read_bytes())
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "daten"


class FakeOpener:
    def __init__(self, failure: str | None = None) -> None:
        self.opened: list[Path] = []
        self.failure = failure

    def reveal(self, file: Path) -> str | None:
        self.opened.append(file)
        return self.failure


def client_with(root: Path, site: Path, opener: FakeOpener) -> httpx.Client:
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True, exist_ok=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(PORT, root, user="anna", folder_opener=opener)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_address_comes_from_links() -> None:
    assert open_folder_url() == "/belege/ordner-oeffnen"


def test_post_with_known_sha256_opens_the_file_of_the_server(root: Path, site: Path) -> None:
    opener = FakeOpener()
    client = client_with(root, site, opener)
    response = client.post(open_folder_url(), data={"sha256": SHA}, headers=ORIGIN)
    assert response.status_code == 303 and response.headers["location"] == "/belege"
    assert opener.opened == [(site / "2025" / "protokoll.html").resolve()]


def test_post_keeps_the_filter(root: Path, site: Path) -> None:
    client = client_with(root, site, FakeOpener())
    response = client.post(
        f"{open_folder_url()}?suche=protokoll&typ=pdf", data={"sha256": SHA}, headers=ORIGIN
    )
    assert response.headers["location"] == "/belege?suche=protokoll&typ=pdf"


def test_unknown_or_missing_sha256_is_404_and_a_path_is_no_identifier(
    root: Path, site: Path
) -> None:
    opener = FakeOpener()
    client = client_with(root, site, opener)
    for data in ({"sha256": "0" * 64}, {}, {"sha256": "2025/protokoll.html"}, {"path": "/etc"}):
        assert client.post(open_folder_url(), data=data, headers=ORIGIN).status_code == 404
    assert opener.opened == []


def test_get_triggers_nothing(root: Path, site: Path) -> None:
    opener = FakeOpener()
    client = client_with(root, site, opener)
    assert client.get(open_folder_url(), params={"sha256": SHA}).status_code == 405
    client.get("/belege")
    assert opener.opened == []


def test_foreign_origin_is_refused(root: Path, site: Path) -> None:
    opener = FakeOpener()
    client = client_with(root, site, opener)
    response = client.post(
        open_folder_url(), data={"sha256": SHA}, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert opener.opened == []


def test_failure_is_a_message_on_the_page(root: Path, site: Path) -> None:
    client = client_with(root, site, FakeOpener(failure="Explorer nicht da."))
    response = client.post(open_folder_url(), data={"sha256": SHA}, headers=ORIGIN)
    assert response.status_code == 409
    assert "Explorer nicht da." in response.text


def test_page_has_the_folder_button_left_of_hide(root: Path, site: Path) -> None:
    client = client_with(root, site, FakeOpener())
    folder = main_of(client, "/belege").split('<small class="pfad">')[1].split("</small>")[0]
    assert 'action="/belege/ordner-oeffnen"' in folder
    assert f'name="sha256" value="{SHA}"' in folder.split("</form>")[0]
    assert 'name="path"' not in folder.split("</form>")[0]
    assert 'aria-label="Ordner öffnen"' in folder
    assert folder.index("Ordner öffnen") < folder.index("Ausblenden")


def test_argument_lists_are_literal() -> None:
    assert wslpath_command(Path("/mnt/c/Belege/a.pdf")) == ["wslpath", "-w", "/mnt/c/Belege/a.pdf"]
    assert explorer_command(r"C:\Belege\a.pdf") == ["explorer.exe", r"/select,C:\Belege\a.pdf"]


def test_opener_converts_then_starts_explorer_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(("run", command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="C:\\Belege\\a.pdf\n")

    def popen(command: list[str], **kwargs: Any) -> None:
        calls.append(("popen", command, kwargs))

    monkeypatch.setattr(explorer.subprocess, "run", run)
    monkeypatch.setattr(explorer.subprocess, "Popen", popen)
    assert ExplorerOpener().reveal(Path("/mnt/c/Belege/a.pdf")) is None
    assert [c[:2] for c in calls] == [
        ("run", ["wslpath", "-w", "/mnt/c/Belege/a.pdf"]),
        ("popen", ["explorer.exe", "/select,C:\\Belege\\a.pdf"]),
    ]
    assert "shell" not in calls[0][2] and "shell" not in calls[1][2]


@pytest.mark.parametrize("failing", ["run", "Popen"])
def test_opener_reports_missing_programs_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    def fine(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="C:\\a.pdf\n")

    def broken(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError(args[0][0])

    monkeypatch.setattr(explorer.subprocess, "run", broken if failing == "run" else fine)
    monkeypatch.setattr(explorer.subprocess, "Popen", broken)
    assert ExplorerOpener().reveal(Path("/x/a.pdf")) == explorer.NOT_AVAILABLE
