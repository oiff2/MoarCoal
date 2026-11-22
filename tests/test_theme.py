"""Palette in `static/tokens.css`: Kontrast WCAG AA, hell und dunkel getrennt (#239).

Als Skript gestartet druckt die Datei die Kontrasttabelle: `uv run python tests/test_theme.py`.
"""

import re
from pathlib import Path

import pytest

TOKENS = (Path(__file__).parents[1] / "src" / "moarcoal" / "static" / "tokens.css").read_text(
    encoding="utf-8"
)
MODES = ["hell", "dunkel"]
SURFACES = [
    "grund",
    "flaeche",
    "flaeche-2",
    "hover",
    "auswahl",
    "seitenleiste-grund",
    "kopfleiste-grund",
]
STATUS = ["fehler", "warnung", "gut"]

# Textfarbe, Hintergrund: jedes Paar, auf dem die Stylesheets Text setzen (mindestens 4,5:1).
TEXT_PAIRS = [
    *[("text", bg) for bg in [*SURFACES, "akzent-weich"]],
    *[("text-gedaempft", bg) for bg in SURFACES],
    *[
        ("akzent", bg)
        for bg in ["grund", "flaeche", "flaeche-2", "hover", "auswahl", "akzent-weich"]
    ],
    ("auf-akzent", "akzent"),
    *[(s, bg) for s in STATUS for bg in ["grund", "flaeche", "flaeche-2", f"{s}-grund"]],
    *[("text", f"{s}-grund") for s in STATUS],
]
# Randlinien von Bedienelementen und Zeichen (WCAG 1.4.11): mindestens 3:1.
SIGN_PAIRS = [
    *[("linie-stark", bg) for bg in ["grund", "flaeche"]],
    *[("akzent", bg) for bg in ["grund", "flaeche"]],
    *[(f"{s}-rand", bg) for s in STATUS for bg in ["grund", "flaeche"]],
]

DECLARATION = re.compile(r"--([\w-]+):\s*([^;]+);")
LIGHT_DARK = re.compile(r"light-dark\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)")


def palette(mode: str) -> dict[str, str]:
    """Token -> Wert im Modus, `var()` und `light-dark()` aufgelöst."""
    css = re.sub(r"/\*.*?\*/", "", TOKENS, flags=re.S)
    root = re.search(r":root\s*\{(.*?)\n\}", css, flags=re.S)
    assert root
    raw = dict(DECLARATION.findall(root.group(1)))
    index = MODES.index(mode)

    def resolve(value: str) -> str:
        value = value.strip()
        ref = re.fullmatch(r"var\(--([\w-]+)\)", value)
        if ref:
            return resolve(raw[ref.group(1)])
        both = LIGHT_DARK.fullmatch(value)
        if both:
            return resolve(both.group(index + 1))
        return value

    return {name: resolve(value) for name, value in raw.items()}


def luminance(hex_colour: str) -> float:
    digits = hex_colour.lstrip("#")
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(fg: str, bg: str) -> float:
    lighter, darker = sorted([luminance(fg), luminance(bg)], reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def ratios(pairs: list[tuple[str, str]], mode: str) -> list[tuple[str, str, float]]:
    colours = palette(mode)
    return [(fg, bg, contrast(colours[fg], colours[bg])) for fg, bg in pairs]


@pytest.mark.parametrize("mode", MODES)
def test_every_text_color_reaches_wcag_aa_on_its_backgrounds(mode: str) -> None:
    too_low = [(fg, bg, round(r, 2)) for fg, bg, r in ratios(TEXT_PAIRS, mode) if r < 4.5]
    assert too_low == []


@pytest.mark.parametrize("mode", MODES)
def test_borders_of_controls_and_signs_reach_three_to_one(mode: str) -> None:
    too_low = [(fg, bg, round(r, 2)) for fg, bg, r in ratios(SIGN_PAIRS, mode) if r < 3]
    assert too_low == []


@pytest.mark.parametrize("mode", MODES)
def test_every_color_token_in_the_pairs_is_a_plain_hex_value(mode: str) -> None:
    colours = palette(mode)
    names = {name for pair in [*TEXT_PAIRS, *SIGN_PAIRS] for name in pair}
    assert [n for n in names if not re.fullmatch(r"#[0-9a-fA-F]{6}", colours[n])] == []


if __name__ == "__main__":
    for m in MODES:
        print(m)
        for fg, bg, r in ratios([*TEXT_PAIRS, *SIGN_PAIRS], m):
            print(f"  {fg:20} auf {bg:20} {r:5.2f}")
