"""Tests: „alle neuen aufnehmen“ im Abschnitt Neu der Belege-Seite (#189; nur tmp_path)."""

import re
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from test_belege_year import ORIGIN, documents, main_of, make_client, section, sha, store_of

from moarcoal.storage import Applied, Change, Rejected
from moarcoal.web.links import site_url

URL = "/belege/alle-aufnehmen"
FILES = ("miete.pdf", "foto.png", "notiz.txt", "bank/auszug.pdf")


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    year = tmp_path / "steuer25"
    (year / "bank").mkdir(parents=True)
    for name in FILES:
        (year / name).write_text(name)
    return make_client(tmp_path, {"steuer25": year})


def post(client: httpx.Client, texts: list[str], url: str = URL) -> httpx.Response:
    """Sendet die Dateien wie das Formular: Ablageort, Pfad und SHA-256 je Datei, wie angezeigt."""
    data = {
        "site": ["steuer25" for _ in texts],
        "path": [t for t in texts],
        "sha256": [sha(t) for t in texts],
    }
    return client.post(url, data=data, headers=ORIGIN)


def shown_form(page: str) -> tuple[str, list[str]]:
    """Adresse und gesendete Prüfsummen des Formulars „alle neuen aufnehmen“."""
    form = page.split(f'action="{URL}', 1)[1]
    action = URL + form.split('"', 1)[0]
    body = form.split("</form>", 1)[0]
    return action, re.findall(r'name="sha256" value="([0-9a-f]{64})"', body)


def test_button_shows_the_count_and_the_text_inside_the_section(client: httpx.Client) -> None:
    neu = section(main_of(client), "neu")
    assert "alle neuen aufnehmen (4)" in neu
    assert "Die Art wird danach je Beleg gesetzt. Es folgen keine Claude-Aufrufe." in neu
    action, shas = shown_form(neu)
    assert action == URL and sorted(shas) == sorted(sha(t) for t in FILES)


def test_button_follows_search_and_type_filter(client: httpx.Client) -> None:
    neu = section(main_of(client, "/belege?typ=pdf"), "neu")
    assert "alle neuen aufnehmen (2)" in neu
    action, shas = shown_form(neu)
    assert "typ=pdf" in action
    assert sorted(shas) == sorted([sha("miete.pdf"), sha("bank/auszug.pdf")])


def test_no_button_without_new_files(client: httpx.Client) -> None:
    neu = section(main_of(client, "/belege?suche=gibtesnicht"), "neu")
    assert "alle neuen aufnehmen" not in neu


def test_takes_all_shown_files_as_belege_in_one_vorgang(client: httpx.Client) -> None:
    store = store_of(client)
    calls: list[int] = []
    original = store.apply

    def counting(changes: Sequence[Change]) -> Applied | Rejected:
        calls.append(len(changes))
        return original(changes)

    store.apply = counting  # type: ignore[method-assign]
    response = post(client, list(FILES))
    assert response.status_code == 303 and response.headers["location"] == site_url()
    assert calls == [4]  # ein apply, vier Dokumente
    found = documents(client)
    assert [d.path for d in found] == sorted(FILES)
    assert all(d.document_kind is None and d.owner == "anna" for d in found)
    assert "alle neuen aufnehmen" not in section(main_of(client), "neu")


def test_redirect_keeps_the_filter(client: httpx.Client) -> None:
    response = post(client, ["miete.pdf"], f"{URL}?suche=miete&typ=pdf")
    assert response.headers["location"] == site_url(query="miete", types=["pdf"])
    assert [d.path for d in documents(client)] == ["miete.pdf"]


def test_changed_file_is_skipped_and_reported_the_others_are_taken(
    client: httpx.Client, tmp_path: Path
) -> None:
    (tmp_path / "steuer25" / "miete.pdf").write_text("geaendert")
    response = post(client, ["miete.pdf", "notiz.txt"])
    assert response.status_code == 200
    assert "1 Beleg aufgenommen" in response.text and "miete.pdf" in response.text
    assert [d.path for d in documents(client)] == ["notiz.txt"]


def test_file_changed_between_display_and_submit_is_reported_as_changed_not_as_gone(
    client: httpx.Client, tmp_path: Path
) -> None:
    _, shown = shown_form(section(main_of(client), "neu"))
    assert sha("miete.pdf") in shown
    (tmp_path / "steuer25" / "miete.pdf").write_text("geaendert")
    response = client.post(
        URL,
        data={
            "site": ["steuer25", "steuer25"],
            "path": ["miete.pdf", "notiz.txt"],
            "sha256": [sha("miete.pdf"), sha("notiz.txt")],
        },
        headers=ORIGIN,
    )
    assert "miete.pdf: Die Datei hat sich seit der Anzeige geändert." in response.text
    assert "nicht mehr in der Ablage" not in response.text
    assert [d.path for d in documents(client)] == ["notiz.txt"]


def test_vanished_file_is_reported_as_gone(client: httpx.Client, tmp_path: Path) -> None:
    (tmp_path / "steuer25" / "miete.pdf").unlink()
    response = post(client, ["miete.pdf", "notiz.txt"])
    assert "miete.pdf: Die Datei ist nicht mehr in der Ablage." in response.text
    assert [d.path for d in documents(client)] == ["notiz.txt"]


def test_form_sends_site_path_and_sha256_of_every_shown_file(client: httpx.Client) -> None:
    form = section(main_of(client), "neu").split('class="alle-aufnehmen"', 1)[1].split("</form>")[0]
    assert len(re.findall(r'name="site" value="steuer25"', form)) == len(FILES)
    assert sorted(re.findall(r'name="path" value="([^"]+)"', form)) == sorted(FILES)


def test_nothing_taken_when_every_file_changed(client: httpx.Client, tmp_path: Path) -> None:
    (tmp_path / "steuer25" / "miete.pdf").write_text("geaendert")
    response = post(client, ["miete.pdf"])
    assert response.status_code == 409 and documents(client) == []


def test_unknown_taken_hidden_and_repeated_shas_are_not_taken(client: httpx.Client) -> None:
    post(client, ["notiz.txt"])
    client.post("/belege/ausblenden", data={"sha256": sha("foto.png")}, headers=ORIGIN)
    response = post(client, ["notiz.txt", "foto.png", "miete.pdf", "miete.pdf", "gibtesnicht"])
    assert response.status_code == 200
    assert [d.path for d in documents(client)] == ["miete.pdf", "notiz.txt"]


def test_get_changes_nothing(client: httpx.Client) -> None:
    assert client.get(URL).status_code == 405
    assert documents(client) == []
