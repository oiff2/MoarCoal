"""Glossar-Prüfungen des schnellen Testkerns (docs/grundgeruest.md, Abschnitt 9).

Alle Prüfungen lesen `CONTEXT.md`. Die Prüffunktionen nehmen ihre Eingaben als Argumente,
damit die Prüfungen selbst mit künstlichen Eingaben getestet werden können.
"""

import ast
import re
import warnings
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CONTEXT = ROOT / "CONTEXT.md"
SRC = ROOT / "src" / "moarcoal"
TEMPLATES = SRC / "templates"

# Wörter aus _Avoid_-Zeilen, die im sichtbaren Text der Vorlagen trotzdem stehen dürfen.
TEMPLATE_EXCEPTIONS = {"warnung", "fehler", "e-kennung"}  # Schweregrade; Wendung „E-Kennung“

# `Code:`-Namen aus CONTEXT.md, die noch nicht im App-Code gebaut sind. Gebaute Namen müssen hier
# raus (der Test schlägt sonst fehl), ebenso Namen, die nicht mehr in CONTEXT.md stehen.
NOT_YET_BUILT = {
    "ExtractionTemplate",
    "Proposal",
    "Snapshot",
    "Source",
}

COINED_LIMIT = 30


# --- Einlesen von CONTEXT.md ---------------------------------------------------------------


def avoid_words(context: str) -> set[str]:
    """Alle Wörter und Wendungen aus _Avoid_-Zeilen, kleingeschrieben."""
    words: set[str] = set()
    for line in context.splitlines():
        if not line.startswith("_Avoid_:"):
            continue
        text = re.sub(r"\([^)]*\)", "", line.removeprefix("_Avoid_:"))
        for chunk in re.split(r"[;,]", text):
            quoted = re.findall(r"„([^“]+)“", chunk)
            parts = quoted or [chunk]
            for part in parts:
                for word in re.split(r"\s+oder\s+", part.strip()):
                    word = word.strip().removesuffix(" allein").strip(" .„“")
                    if word:
                        words.add(word.lower())
    return words


def code_names(context: str) -> set[str]:
    """Namen aus `(Code: `Name`)` und ähnlichen Klammern, die „Code“ nennen."""
    names: set[str] = set()
    for group in re.findall(r"\(([^()]*)\)", context):
        if "Code" in group:
            names.update(re.findall(r"`([A-Z]\w*)`", group))
    return names


def coined_terms(context: str) -> int:
    return sum(
        1 for line in context.splitlines() if line.startswith("**") and "_(geprägt)_" in line
    )


# --- Lesen des App-Codes und der Vorlagen -----------------------------------------------------


def defined_types(source_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in source_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef | ast.TypeAlias):
                names.add(node.name.id if isinstance(node, ast.TypeAlias) else node.name)  # pyright: ignore[reportAttributeAccessIssue]
    return names


class _VisibleText(HTMLParser):
    VISIBLE_ATTRIBUTES = {"title", "alt", "placeholder", "aria-label"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._hidden += 1
        self.parts.extend(v for k, v in attrs if k in self.VISIBLE_ATTRIBUTES and v)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def visible_text(template_source: str) -> str:
    without_jinja = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", " ", template_source, flags=re.S)
    parser = _VisibleText()
    parser.feed(without_jinja)
    return " ".join(parser.parts)


# --- Prüfungen --------------------------------------------------------------------------------


def avoided_in_text(text: str, avoid: set[str], exceptions: set[str]) -> list[str]:
    for phrase in exceptions:  # erlaubte Wendungen vor der Prüfung ausblenden
        text = re.sub(re.escape(phrase), " ", text, flags=re.I)
    return sorted(
        word
        for word in avoid - exceptions
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, flags=re.I)
    )


def camel_parts(name: str) -> list[str]:
    return [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", name)]


def avoided_type_names(names: set[str], avoid: set[str], declared: set[str]) -> list[str]:
    """Typnamen mit gemiedenem Bestandteil; ein Wort, das selbst `Code:`-Name ist, gilt nicht."""
    avoid = avoid - {name.lower() for name in declared}
    return sorted(name for name in names if avoid.intersection(camel_parts(name)))


def code_name_problems(declared: set[str], built: set[str], not_yet_built: set[str]) -> list[str]:
    problems: list[str] = []
    for name in sorted(declared - built - not_yet_built):
        problems.append(f"`{name}` steht in CONTEXT.md, fehlt im Code und nicht in NOT_YET_BUILT")
    for name in sorted(not_yet_built & built):
        problems.append(f"`{name}` ist gebaut, steht aber noch in NOT_YET_BUILT; Liste kürzen")
    for name in sorted(not_yet_built - declared):
        problems.append(f"`{name}` in NOT_YET_BUILT steht nicht mehr in CONTEXT.md; Liste kürzen")
    return problems


def warn_if_too_many_coined(count: int) -> None:
    if count > COINED_LIMIT:
        warnings.warn(
            f"{count} geprägte Begriffe in CONTEXT.md (Obergrenze {COINED_LIMIT}); "
            "Skill `glossar-review` laufen lassen.",
            stacklevel=2,
        )


# --- Tests gegen das echte Repo ---------------------------------------------------------------


@pytest.fixture(scope="module")
def context() -> str:
    return CONTEXT.read_text(encoding="utf-8")


def test_no_avoid_words_in_templates(context: str) -> None:
    avoid = avoid_words(context)
    assert avoid, "keine _Avoid_-Wörter gefunden, Parser kaputt?"
    for template in sorted(TEMPLATES.rglob("*.html")):
        text = visible_text(template.read_text(encoding="utf-8"))
        found = avoided_in_text(text, avoid, TEMPLATE_EXCEPTIONS)
        assert not found, f"{template.name} enthält gemiedene Wörter: {found}"


def test_code_names_exist(context: str) -> None:
    declared = code_names(context)
    assert declared, "keine Code:-Namen gefunden, Parser kaputt?"
    problems = code_name_problems(declared, defined_types(SRC), NOT_YET_BUILT)
    assert not problems, "\n".join(problems)


def test_no_type_with_avoided_name(context: str) -> None:
    names = defined_types(SRC)
    assert avoided_type_names(names, avoid_words(context), code_names(context)) == []


def test_coined_terms_limit(context: str) -> None:
    warn_if_too_many_coined(coined_terms(context))


# --- Tests der Prüfungen selbst -----------------------------------------------------------


SAMPLE = """\
**Modulanmeldung** _(geprägt)_:
Text (Code: `ModuleRegistration`).
_Avoid_: Registry, Manifest, Plugin-Deklaration; „Anmeldung“ allein (klingt nach Login)

**Befund** _(geprägt)_:
Text (Code für den Stichtag: `KeyDate`; Code: `ExposedValue`, nur hier).
_Avoid_: Issue, Warnung oder Fehler (allein, das sind Schweregrade), offener Beleg
"""


def test_parser_reads_avoid_words() -> None:
    assert avoid_words(SAMPLE) == {
        "registry",
        "manifest",
        "plugin-deklaration",
        "anmeldung",
        "issue",
        "warnung",
        "fehler",
        "offener beleg",
    }


def test_parser_reads_code_names() -> None:
    assert code_names(SAMPLE) == {"ModuleRegistration", "KeyDate", "ExposedValue"}


def test_avoid_word_in_template_is_found_but_not_exceptions_or_markup() -> None:
    avoid = avoid_words(SAMPLE)
    html = '<p class="issue">Ein Issue und eine Warnung</p><script>var registry;</script>'
    html += "{# Manifest #}"
    text = visible_text(html)
    assert avoided_in_text(text, avoid, TEMPLATE_EXCEPTIONS) == ["issue"]


def test_exception_phrase_hides_only_the_phrase() -> None:
    exceptions = {"e-kennung"}
    assert avoided_in_text("Die E-Kennung der Zeile", {"kennung"}, exceptions) == []
    assert avoided_in_text("Die Kennung der Zeile", {"kennung"}, exceptions) == ["kennung"]
    assert avoided_in_text("E-Kennung und Kennung", {"kennung"}, exceptions) == ["kennung"]


def test_avoid_word_only_matches_whole_words() -> None:
    assert avoided_in_text("Modulanmeldung", {"anmeldung"}, set()) == []
    assert avoided_in_text("Eine Anmeldung.", {"anmeldung"}, set()) == ["anmeldung"]


def test_type_name_with_avoided_component_is_found() -> None:
    avoid = avoid_words(SAMPLE)
    names = {"ModuleRegistry", "ModuleRegistration", "MyManifest"}
    assert avoided_type_names(names, avoid, set()) == ["ModuleRegistry", "MyManifest"]


def test_avoid_word_that_is_a_code_name_is_not_avoided_for_types() -> None:
    avoid = {"snapshot", "plugin"}
    declared = {"Snapshot"}
    assert avoided_type_names({"Snapshot"}, avoid, declared) == []
    assert avoided_type_names({"PluginThing", "Snapshot"}, avoid, declared) == ["PluginThing"]


def test_code_name_check_fails_when_built_name_stays_on_list() -> None:
    problems = code_name_problems({"Period"}, built={"Period"}, not_yet_built={"Period"})
    assert problems and "Liste kürzen" in problems[0]


def test_code_name_check_fails_for_missing_name_not_on_list() -> None:
    assert code_name_problems({"Period"}, built=set(), not_yet_built=set())


def test_code_name_check_fails_for_list_entry_gone_from_context() -> None:
    assert code_name_problems(set(), built=set(), not_yet_built={"Period"})


def test_code_name_check_passes_when_consistent() -> None:
    assert code_name_problems({"A", "B"}, built={"A"}, not_yet_built={"B"}) == []


def test_defined_types_finds_classes(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("class Foo:\n    class Inner: ...\n")
    assert defined_types(tmp_path) == {"Foo", "Inner"}


def test_too_many_coined_terms_warn() -> None:
    with pytest.warns(UserWarning, match="glossar-review"):
        warn_if_too_many_coined(COINED_LIMIT + 1)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_too_many_coined(COINED_LIMIT)


def test_coined_terms_counts_entries() -> None:
    assert coined_terms(SAMPLE) == 2
