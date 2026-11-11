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
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

E_KENNUNG_RE = re.compile(r"E\d{7}$")
# `fields(name)` in label/for and ids, `fields[name]` in input/name.
FIELD_NAME_RE = re.compile(r"fields[\[(]([A-Za-z0-9_]+)[\])]$")
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
        if tag in ("input", "select", "textarea") and (name := field_name(attributes.get("name"))):
            self._add(name, self._group_label)

    def handle_endtag(self, tag: str) -> None:
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
    return list(parser.fields.values())


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


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: elster_page_fields.py <page.htm>...", file=sys.stderr)
        return 2
    for path in argv:
        if len(argv) > 1:
            print(f"# {Path(path).name}")
        html = Path(path).read_text(encoding="utf-8", errors="replace")
        print("\n".join(format_fields(read_page(html))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
