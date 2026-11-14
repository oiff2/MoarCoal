"""Befunde ausblenden: Ausblendung je Nutzer, Fingerabdruck, Befundliste und Seite (Spec 3.5)."""

import datetime
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.registration import ModuleRegistration
from moarcoal.storage import Dismissal, EntryAddress, open_store
from moarcoal.values.findings import Finding, Severity, split_findings
from moarcoal.values.model import Period, ValueKey, ValueRef

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
REF = ValueRef(ValueKey("demo.value"), "anna", Period.year(2025), None)


class Source:
    """Befundquelle des Test-Moduls: `state` bestimmt den Fingerabdruck."""

    def __init__(self) -> None:
        self.state = "a"
        self.severity = Severity.WARNING

    def __call__(self, state: object, values: object, year: int) -> list[Finding]:
        return [
            Finding(
                "demo.problem",
                self.severity,
                REF,
                "Etwas stimmt nicht.",
                fingerprint=f"stand-{self.state}",
            )
        ]


def make_client(root: Path, source: Source, user: str = "anna") -> httpx.Client:
    module = ModuleRegistration(
        key="demo",
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        findings=source,
    )
    app = make_app(PORT, root, modules=[module], user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def stored(root: Path) -> list[Dismissal]:
    return open_store(root, []).state().of_kind(Dismissal)


@pytest.fixture
def source() -> Source:
    return Source()


def form(source: Source, **overrides: str) -> dict[str, str]:
    finding = source(None, None, 2025)[0]
    fields = {
        "year": "2025",
        "kind": finding.kind,
        "target": finding.identity[1],
        "fingerprint": finding.fingerprint,
        "note": "Geklärt mit dem Amt.",
    }
    return {**fields, **overrides}


def test_dismissed_finding_is_gone_and_counted(tmp_path: Path, source: Source) -> None:
    client = make_client(tmp_path, source)
    assert "Etwas stimmt nicht." in client.get("/befunde?year=2025").text

    response = client.post("/befunde/ausblenden", data=form(source), headers=ORIGIN)

    assert response.status_code == 303
    assert response.headers["location"] == "/befunde?year=2025"
    page = client.get("/befunde?year=2025").text
    assert "Etwas stimmt nicht." not in page
    assert "1 Befund(e) ausgeblendet" in page
    shown = client.get("/befunde?year=2025&ausgeblendet=1").text
    assert "Etwas stimmt nicht." in shown and "Geklärt mit dem Amt." in shown
    assert "Einblenden" in shown


def test_hidden_errors_are_counted_separately(tmp_path: Path, source: Source) -> None:
    source.severity = Severity.ERROR
    client = make_client(tmp_path, source)

    client.post("/befunde/ausblenden", data=form(source), headers=ORIGIN)

    assert "darunter 1 Fehler" in client.get("/befunde?year=2025").text


def test_changed_fingerprint_brings_the_finding_back_with_the_old_note(
    tmp_path: Path, source: Source
) -> None:
    client = make_client(tmp_path, source)
    client.post("/befunde/ausblenden", data=form(source), headers=ORIGIN)

    source.state = "b"
    page = client.get("/befunde?year=2025").text

    assert "Etwas stimmt nicht." in page
    assert "war ausgeblendet: Geklärt mit dem Amt." in page
    assert len(stored(tmp_path)) == 1  # die alte Ausblendung bleibt gespeichert


def test_dismissal_without_note_is_rejected_and_keeps_the_input(
    tmp_path: Path, source: Source
) -> None:
    client = make_client(tmp_path, source)

    for note in ("", "   "):
        response = client.post("/befunde/ausblenden", data=form(source, note=note), headers=ORIGIN)
        assert response.status_code == 422
        assert "gehört eine Notiz" in response.text
    assert stored(tmp_path) == []
    assert "Etwas stimmt nicht." in client.get("/befunde?year=2025").text


def test_dismissal_survives_restart(tmp_path: Path, source: Source) -> None:
    make_client(tmp_path, source).post("/befunde/ausblenden", data=form(source), headers=ORIGIN)

    restarted = make_client(tmp_path, source)

    assert "Etwas stimmt nicht." not in restarted.get("/befunde?year=2025").text


def test_dismissal_of_one_user_does_not_hide_for_another(tmp_path: Path, source: Source) -> None:
    make_client(tmp_path, source).post("/befunde/ausblenden", data=form(source), headers=ORIGIN)

    other = make_client(tmp_path, source, user="berta")

    assert "Etwas stimmt nicht." in other.get("/befunde?year=2025").text


def test_unhide_deletes_the_dismissal(tmp_path: Path, source: Source) -> None:
    client = make_client(tmp_path, source)
    client.post("/befunde/ausblenden", data=form(source), headers=ORIGIN)
    (dismissal,) = stored(tmp_path)

    response = client.post(
        "/befunde/einblenden", data={"year": "2025", "id": dismissal.id}, headers=ORIGIN
    )

    assert response.status_code == 303
    assert stored(tmp_path) == []
    assert "Etwas stimmt nicht." in client.get("/befunde?year=2025").text


def test_unhide_of_a_foreign_dismissal_is_404(tmp_path: Path, source: Source) -> None:
    make_client(tmp_path, source).post("/befunde/ausblenden", data=form(source), headers=ORIGIN)
    (dismissal,) = stored(tmp_path)
    other = make_client(tmp_path, source, user="berta")

    response = other.post(
        "/befunde/einblenden", data={"year": "2025", "id": dismissal.id}, headers=ORIGIN
    )

    assert response.status_code == 404
    assert len(stored(tmp_path)) == 1


def test_dismissal_of_a_stale_fingerprint_is_refused(tmp_path: Path, source: Source) -> None:
    client = make_client(tmp_path, source)
    stale = form(source)
    source.state = "b"

    response = client.post("/befunde/ausblenden", data=stale, headers=ORIGIN)

    assert response.status_code == 409
    assert stored(tmp_path) == []


def test_page_offers_a_form_per_finding(tmp_path: Path, source: Source) -> None:
    page = make_client(tmp_path, source).get("/befunde?year=2025").text

    assert 'action="/befunde/ausblenden"' in page
    assert 'name="note"' in page


def test_finding_without_fingerprint_uses_its_text() -> None:
    a = Finding("demo.k", Severity.NOTE, REF, "Text eins")
    same = Finding("demo.k", Severity.NOTE, REF, "Text eins")
    other = Finding("demo.k", Severity.NOTE, REF, "Text zwei")

    assert a.fingerprint == same.fingerprint != other.fingerprint


def test_entry_target_is_recognised_by_its_address() -> None:
    address = EntryAddress(kind="Document", id="7KQ2M3XA4T")
    finding = Finding("demo.k", Severity.NOTE, address, "Text")

    assert finding.identity == ("demo.k", "Document:7KQ2M3XA4T")


def test_split_matches_on_kind_target_and_fingerprint() -> None:
    finding = Finding("demo.k", Severity.ERROR, REF, "Text")
    kind, target = finding.identity

    def dismissal(**changes: str) -> Dismissal:
        fields = {
            "owner": "anna",
            "finding_kind": kind,
            "target": target,
            "fingerprint": finding.fingerprint,
            "note": "ok",
            "noted_on": datetime.date(2026, 1, 2),
        }
        return Dismissal.model_validate({**fields, **changes})

    assert split_findings([finding], [dismissal()]).hidden_errors == 1
    for changes in ({"fingerprint": "x"}, {"target": "y"}, {"finding_kind": "demo.other"}):
        result = split_findings([finding], [dismissal(**changes)])
        assert result.visible == [finding] and result.hidden == []


def test_dismissal_requires_a_note() -> None:
    with pytest.raises(ValueError):
        Dismissal(
            owner="anna",
            finding_kind="k",
            target="t",
            fingerprint="f",
            note=" ",
            noted_on=datetime.date(2026, 1, 2),
        )
