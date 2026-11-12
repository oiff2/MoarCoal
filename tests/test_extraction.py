"""Claude-Aufruf (docs/grundgeruest.md, Abschnitt 7). Nie das echte `claude`: ein Skript im
Wegwerfverzeichnis spielt es."""

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from moarcoal.extraction import (
    CLAUDE_TOOLS,
    ClaudeExtractor,
    Extracted,
    ExtractionFailed,
    FailureReason,
    FakeExtractor,
    check_answer,
    claude_command,
    tools_reported_finding,
)
from moarcoal.values.findings import Severity

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tax": {
            "type": "object",
            "properties": {"value": {"type": ["string", "number", "null"]}, "location": {}},
            "required": ["value", "location"],
        }
    },
    "required": ["tax"],
}
GOOD = {"tax": {"value": "1.234,00", "location": "Seite 1, Zeile 3"}}

FAKE_CLAUDE = """#!{python}
import json, os, sys
record = {{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "listing": os.listdir("."),
    "stdin": json.loads(sys.stdin.readline()),
}}
open({record!r}, "w").write(json.dumps(record))
print(json.dumps({{"type": "system", "subtype": "init", "tools": {tools}, "mcp_servers": []}}))
{body}
"""


def fake_claude(tmp_path: Path, *, tools: list[str] | None = None, body: str = "") -> Path:
    script = tmp_path / "claude"
    script.write_text(
        FAKE_CLAUDE.format(
            python=sys.executable,
            record=str(tmp_path / "record.json"),
            tools=tools or [],
            body=body,
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def answering(payload: object) -> str:
    event = {"type": "result", "subtype": "success", "is_error": False, "result": payload}
    return f"print(json.dumps({event!r}))"


def run(executable: Path, **kwargs: Any) -> Extracted | ExtractionFailed:
    extractor = ClaudeExtractor(str(executable), **kwargs)
    return extractor.extract(b"%PDF-1.4 erfunden", "application/pdf", SCHEMA, "Steuerbetrag")


def test_argument_list_is_literal() -> None:
    assert claude_command() == [
        "claude",
        "-p",
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]


def test_call_gives_checked_fields_in_empty_throwaway_directory(tmp_path: Path) -> None:
    script = fake_claude(tmp_path, body=answering(json.dumps(GOOD)))
    result = run(script)
    assert isinstance(result, Extracted)
    assert result.fields["tax"].value == "1.234,00"
    assert result.fields["tax"].location == "Seite 1, Zeile 3"
    assert json.loads(result.raw) == GOOD
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["argv"] == claude_command()[1:]
    assert record["listing"] == []
    assert not os.path.exists(record["cwd"])
    block = record["stdin"]["message"]["content"][0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_image_goes_as_image_block(tmp_path: Path) -> None:
    script = fake_claude(tmp_path, body=answering(json.dumps(GOOD)))
    result = ClaudeExtractor(str(script)).extract(b"png", "image/png", SCHEMA, "")
    assert isinstance(result, Extracted)
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["stdin"]["message"]["content"][0]["type"] == "image"


def test_other_formats_are_rejected_without_a_call(tmp_path: Path) -> None:
    script = fake_claude(tmp_path)
    result = ClaudeExtractor(str(script)).extract(b"x", "application/msword", SCHEMA, "")
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.UNSUPPORTED_FORMAT
    assert "application/msword" in result.message
    assert not (tmp_path / "record.json").exists()


def test_tools_in_init_abort_with_error_finding(tmp_path: Path) -> None:
    script = fake_claude(tmp_path, tools=["Read"], body=answering(json.dumps(GOOD)))
    result = run(script)
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.TOOLS_REPORTED
    finding = tools_reported_finding("ich", 2025)
    assert finding.kind == CLAUDE_TOOLS
    assert finding.severity is Severity.ERROR
    assert "Werkzeuge" in finding.message


def test_foreign_fields_are_dropped() -> None:
    answer = {**GOOD, "evil": {"value": "x", "location": "y"}}
    result = check_answer(json.dumps(answer), SCHEMA)
    assert isinstance(result, Extracted)
    assert set(result.fields) == {"tax"}


@pytest.mark.parametrize(
    "raw",
    [
        "kein json",
        "[1]",
        json.dumps({"tax": {"value": ["liste"], "location": "S. 1"}}),  # gegen das Schema
        json.dumps({"tax": {"value": "1", "location": "S. 1", "extra": 1}}),  # Pydantic
        json.dumps({}),  # Pflichtfeld fehlt
    ],
)
def test_invalid_answer_is_a_failure_not_an_exception(raw: str) -> None:
    result = check_answer(raw, SCHEMA)
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.INVALID_ANSWER
    assert result.raw == raw


def test_fenced_json_is_accepted() -> None:
    assert isinstance(check_answer("```json\n" + json.dumps(GOOD) + "\n```", SCHEMA), Extracted)


def test_timeout_is_a_failure(tmp_path: Path) -> None:
    script = fake_claude(tmp_path, body="import time\ntime.sleep(30)")
    result = run(script, timeout=0.5)
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.TIMEOUT


def test_process_without_answer_is_a_failure(tmp_path: Path) -> None:
    result = run(fake_claude(tmp_path))
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.ABORTED


def test_error_result_is_a_failure(tmp_path: Path) -> None:
    body = "print(json.dumps({'type': 'result', 'is_error': True, 'result': 'boom'}))"
    result = run(fake_claude(tmp_path, body=body))
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.ABORTED


def test_missing_binary_is_a_failure(tmp_path: Path) -> None:
    result = run(tmp_path / "gibt-es-nicht")
    assert isinstance(result, ExtractionFailed)
    assert result.reason is FailureReason.ABORTED


def test_fake_extractor_returns_given_answers_in_order() -> None:
    given = Extracted({}, "{}")
    fake = FakeExtractor([given])
    assert fake.extract(b"x", "application/pdf", SCHEMA, "h") is given
    assert fake.calls == [(b"x", "application/pdf", SCHEMA, "h")]
