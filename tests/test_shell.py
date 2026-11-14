"""Tests: Rahmen der Oberfläche, Kopfleiste und Seitenleiste (docs/grundgeruest.md §6)."""

import json
import re
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.web import year_choices

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


def make_client(root: Path, site: Path | None = None) -> httpx.Client:
    if site is not None:
        sites = root / "common" / "sites.json"
        sites.parent.mkdir(parents=True, exist_ok=True)
        sites.write_text(
            json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}),
            encoding="utf-8",
        )
    return TestClient(make_app(PORT, root), base_url=f"http://127.0.0.1:{PORT}")


def part(page: str, tag: str) -> str:
    """Der erste Block `<tag …>…</tag>` der Seite."""
    return page.split(f"<{tag}", 1)[1].split(f"</{tag}>", 1)[0]


def header_year(page: str) -> str:
    selected = re.search(r'<option value="(\d+)" selected>', part(page, "header"))
    assert selected is not None
    return selected.group(1)


def test_sidebar_lists_modules_under_bereiche_and_belege_aussteller_under_allgemein(
    tmp_path: Path,
) -> None:
    side = part(make_client(tmp_path).get("/").text, "aside")
    bereiche, allgemein = side.split("Bereiche", 1)[1].split("Allgemein", 1)
    assert 'href="/steuerjahr"' in bereiche and 'href="/arbeit"' in bereiche
    assert 'href="/belege"' in allgemein and 'href="/aussteller"' in allgemein
    assert "/befunde" not in side  # Befunde sind kein Eintrag der Seitenleiste
    assert side.count("<svg") >= 4  # jedes Icon als Datei im Repo, eingebunden


def test_sidebar_counts_open_files_at_belege(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "a.txt").write_text("a", encoding="utf-8")
    (site / "b.txt").write_text("b", encoding="utf-8")
    side = part(make_client(tmp_path / "daten", site).get("/").text, "aside")
    assert re.search(r'href="/belege"[^>]*>.*?<b class="anzahl">2</b>', side, re.S)


def test_header_shows_findings_summary_of_the_year_with_link(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "a.txt").write_text("a", encoding="utf-8")
    header = part(make_client(tmp_path / "daten", site).get("/").text, "header")
    assert 'href="/befunde?year=2025"' in header
    assert "2 Hinweise" in header and "Fehler" not in header and "Warnungen" not in header
    assert '<span class="wichtigster">' in header  # der wichtigste Befund als Zeile


def test_header_has_user_menu_with_link_to_personal_details(tmp_path: Path) -> None:
    header = part(make_client(tmp_path).get("/").text, "header")
    assert '<a href="/person">Max Mustermann</a>' in header


def test_global_year_is_chosen_in_the_header_and_used_by_pages(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert header_year(client.get("/").text) == "2025"
    response = client.post(
        "/jahr", data={"year": "2024", "back": "/befunde"}, headers=ORIGIN, follow_redirects=False
    )
    assert (response.status_code, response.headers["location"]) == (303, "/befunde")
    page = client.get("/befunde").text
    assert header_year(page) == "2024"
    assert "<h1>Befunde 2024</h1>" in page


def test_a_page_overrides_the_global_year(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/befunde?year=2023").text
    assert header_year(page) == "2023"
    assert header_year(client.get("/").text) == "2025"


def test_choosing_a_year_rejects_bad_years_and_foreign_targets(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    bad = client.post("/jahr", data={"year": "abc", "back": "/"}, headers=ORIGIN)
    assert bad.status_code == 422
    away = client.post(
        "/jahr",
        data={"year": "2024", "back": "//example.org/"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert (away.status_code, away.headers["location"]) == (303, "/")


def test_year_choices_newest_first_with_the_chosen_year() -> None:
    assert year_choices({2023, 2025}, 2025) == [2025, 2023]
    assert year_choices({2025}, 2019) == [2025, 2019]
    assert len(year_choices(set(range(2000, 2030)), 2001)) == 11


def test_user_menu_offers_light_and_dark_with_system_as_default(tmp_path: Path) -> None:
    menu = part(part(make_client(tmp_path).get("/").text, "header"), "details")
    assert 'class="darstellung"' in menu
    options = re.findall(r'<option value="(\w*)"[^>]*>([^<]+)</option>', menu)
    assert options == [("", "System"), ("dunkel", "Dunkel"), ("hell", "Hell")]


COLOR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\(|\b(?:white|black|gray|grey|crimson|orange"
    r"|darkorange|dodgerblue|green|red|blue|Canvas|CanvasText)\b"
)


def test_colors_live_only_in_the_tokens_of_the_stylesheet() -> None:
    src = Path(__file__).parents[1] / "src" / "moarcoal"
    css = (src / "static" / "app.css").read_text(encoding="utf-8")
    tokens, rest = css.split("/* Ende der Farb-Tokens */", 1)
    assert "light-dark(" in tokens
    assert COLOR.findall(rest) == []
    for template in (src / "templates").rglob("*.html"):
        assert COLOR.findall(template.read_text(encoding="utf-8")) == [], template
