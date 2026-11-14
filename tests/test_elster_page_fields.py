"""Tests for tools/elster_page_fields.py with a made-up page in Mein-ELSTER markup."""

from pathlib import Path
from typing import Any

import elster_page_fields as epf
import pytest

PAGE = """
<html><body>
<h1 data-ipe-type="Page.title">2 - Einnahmen</h1>
<h2>Mieteinnahmen <span>Hilfe zum Begriff anzeigen</span></h2>
<h3>Mieteinnahmen für Wohnungen</h3>
<div data-node-type="InlineMzb">
  <label for="X(0)_fields(eruVEinnWhgEinzE0700201)">Mieteinnahmen<em> (Euro)</em></label>
  <input name="fields[eruVEinnWhgEinzE0700201]" value="999">
</div>
<div class="formItem" data-node-type="Line">
  <div class="formItem__lnr" title="Zeile 15"><span>Zeile &nbsp;</span> 15</div>
  <label for="Startseite(0)_X(0)_fields(eruVEinnWhgSumE0700206)">Summe<em> (Euro)</em></label>
  <input name="fields[eruVEinnWhgSumE0700206]" value="1234">
  <input name="fieldsResetSource[eruVEinnWhgSumE0700206]" type="hidden" value="false">
</div>
<h2>Nutzung</h2>
<div class="formItem" data-node-type="Line">
  <div class="formItem__lnr" title="Zeile 10">10</div>
  <div class="formItem__wrapper" role="group" aria-label="als Ferienwohnung genutzt">
    <input name="fields[eruVAllgNutzungE0700703]" type="radio" value="true">
    <label for="Startseite(0)_X(0)_fields(eruVAllgNutzungE0700703)_0">Ja</label>
    <input name="fields[eruVAllgNutzungE0700703]" type="radio" value="false">
    <label for="Startseite(0)_X(0)_fields(eruVAllgNutzungE0700703)_1">Nein</label>
  </div>
</div>
<div data-node-type="Line">
  <label for="Startseite(0)_X(0)_fields(eruVOhneZeileE0709901)">Hinweis vorhanden.Ohne Zeile</label>
</div>
<input name="fields[eruVOhneKennung]">
</body></html>
"""


def test_reads_kennung_zeile_label_and_headings_once_per_field():
    fields = epf.read_page(PAGE)

    assert [(f.e_kennung, f.line, f.label) for f in fields] == [
        ("E0700201", "", "Mieteinnahmen (Euro)"),
        ("E0700206", "15", "Summe (Euro)"),
        ("E0700703", "10", "als Ferienwohnung genutzt"),
        ("E0709901", "", "Ohne Zeile"),
    ]
    assert fields[1].headings == ("2 - Einnahmen", "Mieteinnahmen", "Mieteinnahmen für Wohnungen")
    assert fields[2].headings == ("2 - Einnahmen", "Nutzung")


def test_output_names_the_field_but_never_a_value():
    output = "\n".join(epf.format_fields(epf.read_page(PAGE)))

    assert "## 2 - Einnahmen / Mieteinnahmen / Mieteinnahmen für Wohnungen" in output
    assert "  Z   15 | E0700206 | eruVEinnWhgSum | Summe (Euro)" in output
    assert "1234" not in output
    assert "999" not in output


def structure_of(*pages: str, year: int = 2025) -> dict[str, Any]:
    return epf.build_structure([(f"seite{i}.htm", p) for i, p in enumerate(pages, 1)], "N", year)


def test_structure_has_schema_page_headings_and_no_values():
    structure = structure_of(PAGE)

    assert (structure["schema"], structure["form"], structure["year"]) == (1, "N", 2025)
    assert structure["provisional"] is False
    assert structure["fields"][1] == {
        "e_kennung": "E0700206",
        "page": "2 - Einnahmen",
        "headings": ["Mieteinnahmen", "Mieteinnahmen für Wohnungen"],
        "line": "15",
        "label": "Summe (Euro)",
    }
    assert "1234" not in str(structure)


def test_structure_keeps_an_e_kennung_once_across_pages_and_names_pages_without_title():
    other = (
        '<div data-node-type="Line"><label for="f(a)_fields(eruXE0100001)">Eins</label>'
        '<input name="fields[eruXE0100001]"></div>'
        '<label for="f(a)_fields(eruVEinnWhgSumE0700206)">Doppelt</label>'
        '<input name="fields[eruVEinnWhgSumE0700206]">'
    )

    fields = structure_of(PAGE, other)["fields"]

    assert [f["e_kennung"] for f in fields].count("E0700206") == 1
    assert fields[-1]["page"] == "seite2"


def field(kennung: str, label: str, line: str = "5") -> dict[str, Any]:
    return {"e_kennung": kennung, "page": "Seite", "headings": ["A"], "line": line, "label": label}


def year_of(*fields: dict[str, Any]) -> dict[str, Any]:
    return {"schema": 1, "form": "N", "year": 2025, "provisional": False, "fields": list(fields)}


def test_diff_reports_all_four_kinds_of_change():
    previous = year_of(
        field("E0000001", "bleibt"),
        field("E0000002", "umbenannt"),
        field("E0000003", "andere Nr.", line="5"),
        field("E0000004", "neue Kennung"),
        field("E0000005", "entfällt"),
    )
    current = year_of(
        field("E0000001", "bleibt"),
        field("E0000002", "anders benannt"),
        field("E0000003", "andere Nr.", line="6"),
        field("E0000044", "neue Kennung"),
        field("E0000006", "kommt neu"),
    )

    assert epf.diff_structures(previous, current) == [
        "Bezeichnung geändert: E0000002: 'umbenannt' -> 'anders benannt'",
        "E-Kennung geändert: E0000004 -> E0000044 (neue Kennung)",
        "Entfallen: E0000005 (Nr. 5, entfällt)",
        "Neu: E0000006 (Nr. 5, kommt neu)",
        "Nr. im Vordruck geändert: E0000003 (andere Nr.): 5 -> 6",
    ]


def test_diff_of_equal_years_and_ambiguous_labels():
    same = year_of(field("E0000001", "Summe"))
    assert epf.diff_structures(same, same) == []

    # Two fields with the same label: no guess which one got the new E-Kennung.
    previous = year_of(field("E0000001", "Summe"), field("E0000002", "Summe"))
    current = year_of(field("E0000011", "Summe"), field("E0000012", "Summe"))
    assert len(epf.diff_structures(previous, current)) == 4


def test_structure_and_diff_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    pages = tmp_path / "seiten"
    pages.mkdir()
    (pages / "1.htm").write_text(PAGE, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    base = ["structure", str(pages), "--form", "N", "--out", str(out)]

    assert epf.main([*base, "--year", "2025"]) == 0
    assert epf.main([*base, "--year", "2026"]) == 0
    capsys.readouterr()
    assert epf.main(["diff", str(out / "n-2025.json"), str(out / "n-2026.json")]) == 0

    assert capsys.readouterr().out.strip() == "Keine Änderungen."


CHOICES = """
<h1 data-ipe-type="Page.title">10 - Arbeitsmittel</h1>
<div data-node-type="Line">
  <label for="X(0)_fields(eruNArtE0204401)">Art der Arbeitsmittel</label>
  <input name="fields[eruNArtE0204401]" value="Geheimer Wert">
  <ul id="X(0)_fields(eruNArtE0204401)_suggestions" role="listbox">
    <li role="option">Büromaterial</li><li role="option">Computer</li>
  </ul>
</div>
<div data-node-type="Line">
  <label for="X(0)_fields(eruNKlasseE0200002)">Steuerklasse</label>
  <select name="fields[eruNKlasseE0200002]">
    <option value=""></option><option value="1" selected>I</option><option value="2">II</option>
  </select>
</div>
<div data-node-type="Line">
  <label for="X(0)_fields(eruNBetragE0204403)">Betrag</label>
  <input name="fields[eruNBetragE0204403]">
</div>
"""


def test_options_of_a_suggestion_list_and_a_select_go_into_the_structure_without_values():
    structure = structure_of(CHOICES)
    art, klasse, betrag = structure["fields"]

    assert art["options"] == ["Büromaterial", "Computer"]
    assert art["free_text"] is True
    assert klasse["options"] == ["I", "II"]
    assert "free_text" not in klasse
    assert "options" not in betrag
    assert "Geheimer Wert" not in str(structure)


def test_diff_reports_a_changed_choice():
    before = year_of(field("E0100001", "Art"))
    after = year_of({**field("E0100001", "Art"), "options": ["Computer"]})

    assert epf.diff_structures(before, after) == ["Auswahl geändert: E0100001 (Art)"]
