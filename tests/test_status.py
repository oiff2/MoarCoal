"""Tests: gemeinsame Statussprache (Schweregrad, Belegstand) und Dateityp-Icons, ein Baustein."""

import re
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from moarcoal.values.findings import Severity
from moarcoal.values.model import Backing
from moarcoal.web.app import TEMPLATES_DIR
from moarcoal.web.previews import preview_kind

STATUS = "_status.html"


def render(macro: str, *args: object) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    globals_: dict[str, Any] = env.globals  # pyright: ignore[reportAssignmentType]
    globals_["preview_kind"] = preview_kind
    module: Any = env.get_template(STATUS).module
    return str(getattr(module, macro)(*args))


@pytest.mark.parametrize("severity", list(Severity))
def test_severity_has_its_own_symbol_class_and_label(severity: Severity) -> None:
    html = render("severity", severity)
    assert f'class="status status-{severity.name.lower()}"' in html
    assert severity.value in html
    assert 'class="symbol"' in html


@pytest.mark.parametrize("backing", list(Backing))
def test_backing_has_its_own_symbol_class_and_label(backing: Backing) -> None:
    html = render("backing", backing)
    assert f'class="status status-{backing.name.lower()}"' in html
    assert backing.label in html
    assert 'class="symbol"' in html


def test_all_status_symbols_differ() -> None:
    pages = [render("severity", s) for s in Severity] + [render("backing", b) for b in Backing]
    symbols = [re.findall(r'class="symbol"[^>]*>([^<]+)<', html)[0] for html in pages]
    assert len(set(symbols)) == len(symbols)


@pytest.mark.parametrize(
    ("path", "icon"),
    [("a/b.PDF", "pdf"), ("x.png", "bild"), ("x.html", "html"), ("x.txt", "sonstige")],
)
def test_file_type_icon_by_suffix(path: str, icon: str) -> None:
    html = render("file_type", path)
    assert f'class="dateityp dateityp-{icon}"' in html
    assert "<svg" in html


def test_no_template_copies_status_classes() -> None:
    """Klassen der Statussprache stehen nur im Baustein."""
    pattern = re.compile(r"schweregrad-|belegstand-|status-|dateityp-")
    offenders = [
        p.relative_to(TEMPLATES_DIR).as_posix()
        for p in Path(TEMPLATES_DIR).rglob("*.html")
        if p.name != STATUS and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_finding_list_groups_by_severity_under_headings() -> None:
    """Befunde stehen je Schweregrad unter einer Überschrift (Symbol, Name, Anzahl), Fehler zuerst."""
    from types import SimpleNamespace

    def finding(severity: Severity, message: str) -> SimpleNamespace:
        return SimpleNamespace(
            severity=severity, message=message, href=None, identity=("k", message)
        )

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    module: Any = env.get_template("_findings.html").module
    findings = [
        finding(Severity.NOTE, "hinweis-a"),
        finding(Severity.ERROR, "fehler-a"),
        finding(Severity.ERROR, "fehler-b"),
    ]
    html = str(module.finding_list(findings))
    headings = re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.S)
    assert len(headings) == 2
    assert "status-error" in headings[0] and "Fehler (2)" in headings[0]
    assert "status-note" in headings[1] and "Hinweis (1)" in headings[1]
    assert "Warnung" not in html
    assert html.index("fehler-b") < html.index("hinweis-a")
    assert html.count('class="symbol"') == 2
