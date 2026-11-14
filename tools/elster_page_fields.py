"""Lists the E-Kennungen of a Mein-ELSTER form page saved by hand.

In Mein ELSTER, open a Teilseite of the return and save it with Ctrl+S as
"Webseite, vollständig". Each field of the saved HTML carries its E-Kennung
at the end of its internal name:

    <div class="formItem__lnr" title="Zeile 15"> ... </div>
    <label for="..._fields(eruVEinnMieteinnWhgSumE0700206)">Summe (Euro)</label>
    <input name="fields[eruVEinnMieteinnWhgSumE0700206]" ...>

Prints heading path, Zeile, E-Kennung, field name and label per field, once
per field name. Never prints a value, so the output can go into issues and
the catalogue. Rows of a list appear only once a row has been added in
Mein ELSTER before saving.

Usage: uv run --no-project python -I tools/elster_page_fields.py <page.htm>...

Structure of a year: reads every page of a folder (in file-name order, so name them in the order
of Mein ELSTER) and writes the structure file of the year into the repo (page, headings, Zeile,
label, E-Kennung per field; never values or names):

    elster_page_fields.py structure <folder> --form N --year 2025 [--out <dir>]

Diff against the previous year, as text without values (new fields, dropped fields, changed
E-Kennung with the same label, changed label or Zeile):

    elster_page_fields.py diff <previous.json> <current.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

E_KENNUNG_RE = re.compile(r"E\d{7}$")
# `fields(name)` in label/for and ids, `fields[name]` in input/name.
FIELD_NAME_RE = re.compile(r"fields[\[(]([A-Za-z0-9_]+)[\])]$")
# The suggestion list of a field with free text: <ul id="..._fields(name)_suggestions">.
SUGGESTIONS_ID_RE = re.compile(r"fields\(([A-Za-z0-9_]+)\)_suggestions$")
LINE_TITLE_RE = re.compile(r"^Zeile\s+(\d+[a-z]?)$")
# Screen-reader texts ELSTER puts into headings and labels.
NOISE = ("Hilfe zum Begriff anzeigen", "Hinweis vorhanden.")
VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)


@dataclass(frozen=True)
class PageField:
    name: str
    e_kennung: str
    line: str
    label: str
    headings: tuple[str, ...]
    # Fixed choices of a selection field (texts, never the chosen one); `free_text`: the field
    # is a suggestion list and also takes an own text.
    options: tuple[str, ...] = ()
    free_text: bool = False


def field_name(attribute: str | None) -> str | None:
    """The field name inside `fields(...)` / `fields[...]`, if it ends in an E-Kennung."""
    if not attribute:
        return None
    match = FIELD_NAME_RE.search(attribute)
    if match and E_KENNUNG_RE.search(match.group(1)):
        return match.group(1)
    return None


def _clean(text: str) -> str:
    for noise in NOISE:
        text = text.replace(noise, "")
    return " ".join(text.split())


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, PageField] = {}
        self._headings: dict[int, str] = {}
        self._heading: tuple[int, list[str]] | None = None
        # Open elements; a Line element remembers its Zeile.
        self._stack: list[tuple[str, bool]] = []
        self._line: str = ""
        # A radio group has no <label> of its own, only an aria-label on its wrapper.
        self._group_label: str = ""
        self._label: tuple[str, list[str]] | None = None
        self._label_depth = 0
        self.options: dict[str, list[str]] = {}
        self.free_text: set[str] = set()
        self._select: str | None = None
        self._suggestions: str | None = None
        self._option: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag not in VOID_TAGS:
            is_line = attributes.get("data-node-type") == "Line"
            if is_line:
                self._line = self._group_label = ""
            self._stack.append((tag, is_line))
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = (int(tag[1]), [])
        title = attributes.get("title") or ""
        if match := LINE_TITLE_RE.match(title.strip()):
            self._line = match.group(1)
        if attributes.get("role") == "group" and (aria := attributes.get("aria-label")):
            self._group_label = _clean(aria)
        if tag == "label" and (name := field_name(attributes.get("for"))):
            self._label, self._label_depth = (name, []), 0
        elif tag == "label" and self._label is not None:
            self._label_depth += 1
        if tag == "select" and (name := field_name(attributes.get("name"))):
            self._select = name
            self.options.setdefault(name, [])
        if tag == "ul" and (match := SUGGESTIONS_ID_RE.search(attributes.get("id") or "")):
            suggested: str = match[1]
            self._suggestions = suggested
            self.options.setdefault(suggested, [])
            self.free_text.add(suggested)
        if tag in ("option", "li") and (self._select or self._suggestions):
            self._option = []
        if tag in ("input", "select", "textarea") and (name := field_name(attributes.get("name"))):
            self._add(name, self._group_label)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("option", "li") and self._option is not None:
            owner = self._select or self._suggestions
            if owner and (text := _clean("".join(self._option))):
                self.options[owner].append(text)
            self._option = None
        if tag == "select":
            self._select = None
        if tag == "ul":
            self._suggestions = None
        if self._heading and tag == f"h{self._heading[0]}":
            level, parts = self._heading
            self._headings = {k: v for k, v in self._headings.items() if k < level}
            self._headings[level] = _clean("".join(parts))
            self._heading = None
        if tag == "label" and self._label is not None:
            if self._label_depth:
                self._label_depth -= 1
            else:
                name, parts = self._label
                self._add(name, _clean("".join(parts)))
                self._label = None
        if tag in VOID_TAGS:
            return
        # Close up to the matching element; HTML in the wild is not always balanced.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                if any(is_line for _, is_line in self._stack[index:]):
                    self._line = self._group_label = ""
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._option.append(data)
        if self._heading:
            self._heading[1].append(data)
        if self._label is not None:
            self._label[1].append(data)

    def _add(self, name: str, label: str) -> None:
        known = self.fields.get(name)
        if known is not None:
            if label and not known.label:
                self.fields[name] = PageField(
                    known.name, known.e_kennung, known.line, label, known.headings
                )
            return
        match = E_KENNUNG_RE.search(name)
        assert match
        headings = tuple(self._headings[k] for k in sorted(self._headings))
        self.fields[name] = PageField(name, match.group(0), self._line, label, headings)


def read_page(html: str) -> list[PageField]:
    """The fields of a saved form page in page order, one per field name."""
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return [
        replace(
            item,
            options=tuple(parser.options.get(item.name, ())),
            free_text=item.name in parser.free_text,
        )
        for item in parser.fields.values()
    ]


def format_fields(fields: list[PageField]) -> list[str]:
    lines: list[str] = []
    last: tuple[str, ...] | None = None
    for item in fields:
        if item.headings != last:
            lines.append("## " + " / ".join(item.headings))
            last = item.headings
        prefix = item.name.removesuffix(item.e_kennung)
        lines.append(f"  Z {item.line:>4} | {item.e_kennung} | {prefix} | {item.label}")
    return lines


SCHEMA = 1  # read by src/moarcoal/modules/tax_year/structure.py
DEFAULT_OUT = Path(__file__).parents[1] / "src/moarcoal/modules/tax_year/strukturen"

type Structure = dict[str, Any]


def build_structure(pages: list[tuple[str, str]], form: str, year: int) -> Structure:
    """The structure of a year from (file name, HTML) pages, in the order given.

    The page is the first heading (Mein ELSTER's page title, else the file name); the other
    headings follow. An E-Kennung appears once; a later page repeating it is ignored.
    """
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, html in pages:
        for item in read_page(html):
            if item.e_kennung in seen:
                continue
            seen.add(item.e_kennung)
            page, *headings = item.headings or (Path(name).stem,)
            entry: dict[str, Any] = {
                "e_kennung": item.e_kennung,
                "page": page,
                "headings": headings,
                "line": item.line,
                "label": item.label,
            }
            if item.options:
                entry["options"] = list(item.options)
                if item.free_text:
                    entry["free_text"] = True
            fields.append(entry)
    return {"schema": SCHEMA, "form": form, "year": year, "provisional": False, "fields": fields}


def diff_structures(previous: Structure, current: Structure) -> list[str]:
    """What changed from one year's structure to the next, as text without values.

    Fields match by E-Kennung (then a changed label or Zeile is reported). The rest match by
    page, headings and label when that is unambiguous on both sides (a changed E-Kennung);
    whatever is left is dropped or new.
    """
    old = {f["e_kennung"]: f for f in previous["fields"]}
    new = {f["e_kennung"]: f for f in current["fields"]}

    def where(f: dict[str, Any]) -> str:
        return f"{f['e_kennung']} (Nr. {f['line'] or '-'}, {f['label']})"

    def identity(f: dict[str, Any]) -> tuple[Any, ...]:
        return (f["page"], tuple(f["headings"]), f["label"])

    lines: list[str] = []
    for kennung in old.keys() & new.keys():
        before, after = old[kennung], new[kennung]
        if before["label"] != after["label"]:
            lines.append(
                f"Bezeichnung geändert: {kennung}: '{before['label']}' -> '{after['label']}'"
            )
        if before.get("options", []) != after.get("options", []):
            lines.append(f"Auswahl geändert: {kennung} ({after['label']})")
        if before["line"] != after["line"]:
            lines.append(
                f"Nr. im Vordruck geändert: {kennung} ({after['label']}): "
                f"{before['line'] or '-'} -> {after['line'] or '-'}"
            )
    gone = [f for k, f in old.items() if k not in new]
    added = [f for k, f in new.items() if k not in old]
    for field in list(gone):
        twins = [f for f in added if identity(f) == identity(field)]
        same = [f for f in gone if identity(f) == identity(field)]
        if len(twins) == 1 and len(same) == 1:
            lines.append(
                f"E-Kennung geändert: {field['e_kennung']} -> {twins[0]['e_kennung']} "
                f"({field['label']})"
            )
            gone.remove(field)
            added.remove(twins[0])
    lines += [f"Entfallen: {where(f)}" for f in gone]
    lines += [f"Neu: {where(f)}" for f in added]
    return sorted(lines)


def _structure_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="elster_page_fields.py structure")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--form", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    paths = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in (".htm", ".html"))
    if not paths:
        print(f"Keine Seiten in {args.folder}", file=sys.stderr)
        return 1
    pages = [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in paths]
    structure = build_structure(pages, args.form, args.year)
    target = args.out / f"{args.form.lower()}-{args.year}.json"
    target.write_text(json.dumps(structure, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{target}: {len(structure['fields'])} Felder")
    return 0


def _diff_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="elster_page_fields.py diff")
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args(argv)
    previous, current = (
        json.loads(path.read_text(encoding="utf-8")) for path in (args.previous, args.current)
    )
    print("\n".join(diff_structures(previous, current)) or "Keine Änderungen.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "Usage: elster_page_fields.py <page.htm>... | structure ... | diff ...",
            file=sys.stderr,
        )
        return 2
    if argv[0] == "structure":
        return _structure_command(argv[1:])
    if argv[0] == "diff":
        return _diff_command(argv[1:])
    for path in argv:
        if len(argv) > 1:
            print(f"# {Path(path).name}")
        html = Path(path).read_text(encoding="utf-8", errors="replace")
        print("\n".join(format_fields(read_page(html))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
