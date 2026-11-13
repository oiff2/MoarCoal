"""Blocks real personal data before it reaches git or GitHub.

Modes:
  staged         scan added lines of the staged diff (git pre-commit hook)
  file PATH...   scan files, e.g. the commit message (git commit-msg hook)
  claude-hook    read a Claude Code PreToolUse event from stdin and block
                 `gh` commands whose text (or --body-file) contains findings

Checks: local denylist (outside the repo, plus the one the app derives into its data
directory), IBAN with mod-97 checksum,
Steuer-ID with ISO 7064 check digit, Steuernummer in slash format, e-mail
addresses outside example domains. Values in the repo allowlist pass.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "tools" / "erlaubte_beispielwerte.txt"
DENYLIST_PATH = Path(
    os.environ.get(
        "MOARCOAL_SPERRLISTE",
        Path.home() / ".config" / "moarcoal" / "sperrliste.txt",
    )
)


def derived_denylist_path() -> Path:
    """`common/derived-denylist.txt` im Datenverzeichnis (`MOARCOAL_DATA_DIR` oder `~/MoarCoal`).
    Die Datei schreibt die App aus den sensiblen Feldern; fehlt sie, zählt nur die handgepflegte."""
    root = os.environ.get("MOARCOAL_DATA_DIR")
    return (Path(root) if root else Path.home() / "MoarCoal") / "common" / "derived-denylist.txt"


IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")
STEUER_ID_RE = re.compile(r"(?<!\d)\d{2} ?\d{3} ?\d{3} ?\d{3}(?!\d)")
STEUERNUMMER_RE = re.compile(r"(?<![\d/])\d{2,3}/\d{3,4}/\d{4,5}(?![\d/])")
# Files whose added lines are not scanned (exact repo-relative path): lock file
# hashes contain digit runs that look like a Steuer-ID.
SKIPPED_FILES = frozenset({"uv.lock"})

EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")
ALLOWED_EMAIL_DOMAINS = re.compile(
    r"(^|\.)(example\.(com|org|net|de)|test|invalid|localhost"
    r"|users\.noreply\.github\.com)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    kind: str
    value: str
    where: str

    def __str__(self) -> str:
        return f"{self.where}: {self.kind}: {self.value}"


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def load_values(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def iban_valid(raw: str) -> bool:
    iban = raw.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def steuer_id_valid(raw: str) -> bool:
    tin = raw.replace(" ", "")
    if len(tin) != 11 or tin[0] == "0":
        return False
    product = 10
    for c in tin[:10]:
        total = (int(c) + product) % 10 or 10
        product = (total * 2) % 11
    check = (11 - product) % 10
    return check == int(tin[10])


def scan(text: str, where: str, allow: list[str], deny: list[str]) -> list[Finding]:
    allowed = {normalize(v) for v in allow}
    findings: list[Finding] = []

    def add(kind: str, value: str) -> None:
        if normalize(value) not in allowed:
            findings.append(Finding(kind, value, where))

    flat = normalize(text)
    for value in deny:
        if normalize(value) in flat:
            findings.append(Finding("Sperrliste", "<Wert aus Sperrliste>", where))
    for m in IBAN_RE.finditer(text):
        if iban_valid(m.group()):
            add("IBAN", m.group())
    for m in STEUER_ID_RE.finditer(text):
        if steuer_id_valid(m.group()):
            add("Steuer-ID", m.group())
    for m in STEUERNUMMER_RE.finditer(text):
        add("Steuernummer", m.group())
    for m in EMAIL_RE.finditer(text):
        if not ALLOWED_EMAIL_DOMAINS.search(m.group(1)):
            add("E-Mail", m.group())
    return findings


def staged_added_lines() -> list[tuple[str, str]]:
    """(file, added line) pairs from the staged diff."""
    out = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--no-color", "--diff-filter=d"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout
    return parse_added_lines(out)


def parse_added_lines(diff: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    current = "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++") and current not in SKIPPED_FILES:
            lines.append((current, line[1:]))
    return lines


def body_files(command: str) -> list[Path]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    paths: list[Path] = []
    for i, tok in enumerate(tokens):
        if tok in ("--body-file", "-F") and i + 1 < len(tokens):
            paths.append(Path(tokens[i + 1]))
        elif tok.startswith("--body-file="):
            paths.append(Path(tok.split("=", 1)[1]))
    return [p for p in paths if str(p) != "-"]


def report(findings: list[Finding]) -> None:
    print("Datenschutz-Prüfung: mögliche echte Daten gefunden:", file=sys.stderr)
    for f in findings:
        print(f"  {f}", file=sys.stderr)
    print(
        "Durch erfundene Beispielwerte ersetzen. Ist ein Wert bewusst erfunden, "
        f"in {ALLOWLIST_PATH.relative_to(REPO_ROOT)} eintragen.",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    allow = load_values(ALLOWLIST_PATH)
    deny = load_values(DENYLIST_PATH) + load_values(derived_denylist_path())
    mode = argv[1] if len(argv) > 1 else ""
    findings: list[Finding] = []

    if mode == "staged":
        for path, line in staged_added_lines():
            findings += scan(line, path, allow, deny)
        blocked_exit = 1
    elif mode == "file":
        for name in argv[2:]:
            text = Path(name).read_text(encoding="utf-8", errors="replace")
            text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
            findings += scan(text, name, allow, deny)
        blocked_exit = 1
    elif mode == "claude-hook":
        event = json.load(sys.stdin)
        command = event.get("tool_input", {}).get("command", "")
        if not re.search(r"(^|[\s;&|(])gh\s", command):
            return 0
        findings += scan(command, "gh-Befehl", allow, deny)
        cwd = Path(event.get("cwd") or ".")
        for p in body_files(command):
            full = p if p.is_absolute() else cwd / p
            if full.is_file():
                findings += scan(
                    full.read_text(encoding="utf-8", errors="replace"), str(p), allow, deny
                )
        blocked_exit = 2  # exit code 2 blocks the tool call, stderr goes to Claude
    else:
        print(__doc__, file=sys.stderr)
        return 64

    if findings:
        report(findings)
        return blocked_exit
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
