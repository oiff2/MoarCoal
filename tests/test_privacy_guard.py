"""Tests for tools/privacy_guard.py.

Test values that would trip the guard are built at runtime, so this file
itself passes the pre-commit check.
"""

import io
import json
from pathlib import Path

import privacy_guard as pg
import pytest


def make_iban(bank_and_account: str) -> str:
    """Valid German IBAN for an 18-digit BLZ+account string."""
    check = 98 - int(bank_and_account + "131400") % 97
    return f"DE{check:02d}{bank_and_account}"


def make_steuer_id(first10: str) -> str:
    for c in "0123456789":
        if pg.steuer_id_valid(first10 + c):
            return first10 + c
    raise AssertionError("no check digit")


IBAN = make_iban("500105175407324931")
TIN = make_steuer_id("4710815123")


def kinds(text: str, allow: list[str] | None = None, deny: list[str] | None = None) -> list[str]:
    return [f.kind for f in pg.scan(text, "t", allow or [], deny or [])]


def test_known_examples_validate() -> None:
    assert pg.iban_valid("DE89 3704 0044 0532 0130 00")
    assert pg.steuer_id_valid("86095742719")
    assert not pg.steuer_id_valid("86095742718")


def test_valid_iban_found_with_and_without_spaces() -> None:
    spaced = " ".join(IBAN[i : i + 4] for i in range(0, len(IBAN), 4))
    assert kinds(f"Konto {IBAN}") == ["IBAN"]
    assert kinds(f"Konto {spaced}.") == ["IBAN"]


def test_iban_with_wrong_checksum_ignored() -> None:
    broken = IBAN[:-1] + str((int(IBAN[-1]) + 1) % 10)
    assert "IBAN" not in kinds(broken)


def test_steuer_id_found() -> None:
    assert kinds(f"ID {TIN}") == ["Steuer-ID"]
    assert kinds(f"ID {TIN[:2]} {TIN[2:5]} {TIN[5:8]} {TIN[8:]}") == ["Steuer-ID"]


def test_steuernummer_slash_format() -> None:
    assert kinds("StNr " + "/".join(["217", "5432", "10987"])) == ["Steuernummer"]
    assert kinds("Datum 2026/11/09") == []


def test_email_outside_example_domains() -> None:
    assert kinds("max@" + "beispielmail.de") == ["E-Mail"]
    assert kinds("max@example.org, a@b.test, 1+x@users.noreply.github.com") == []


def test_allowlist_passes_values() -> None:
    assert kinds(f"Konto {IBAN}", allow=[IBAN.lower()]) == []


def test_denylist_matches_ignoring_case_and_spaces_without_echoing() -> None:
    findings = pg.scan("wohnt in der Musterweg 12", "t", [], ["musterweg12"])
    assert [f.kind for f in findings] == ["Sperrliste"]
    assert "Musterweg" not in str(findings[0])


def run_claude_hook(monkeypatch: pytest.MonkeyPatch, command: str, cwd: str = ".") -> int:
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    monkeypatch.setattr(pg, "DENYLIST_PATH", pg.REPO_ROOT / "nonexistent")
    return pg.main(["x", "claude-hook"])


def test_claude_hook_blocks_gh_with_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_claude_hook(monkeypatch, f'gh issue create --body "IBAN {IBAN}"') == 2


def test_claude_hook_ignores_non_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_claude_hook(monkeypatch, f"echo {IBAN}") == 0


def test_claude_hook_scans_body_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "body.md").write_text(f"Steuer-ID {TIN}\n", encoding="utf-8")
    assert run_claude_hook(monkeypatch, "gh pr create --body-file body.md", str(tmp_path)) == 2
