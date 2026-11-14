"""Struktur der Anlage N je Jahr: Laden, Verweise des Katalogs, strenge Vorjahres-Zuordnung."""

import json
from collections.abc import Mapping
from dataclasses import replace

import elster_page_fields as epf
import pytest

from moarcoal.modules.tax_year.anlage_n import FIELDS_2025, FORMS, STRUCTURES, fields_n
from moarcoal.modules.tax_year.fields import NEW_FIELD, FormField, check_previous_years
from moarcoal.modules.tax_year.structure import (
    DIRECTORY,
    FormStructure,
    StructureField,
    UnknownElsterId,
    load_structure,
    parse_structure,
)


def test_every_catalog_field_exists_in_the_structure_of_its_year():
    for year, fields in FORMS.items():
        structure = STRUCTURES[year]
        for field in fields:
            assert field.elster_id is not None
            described = structure.get(field.elster_id)
            assert (field.form_line, field.label) == (described.line, described.label)


def test_a_missing_e_kennung_is_an_error_not_a_gap():
    thin = FormStructure("N", 2025, True, STRUCTURES[2025].fields[1:])

    with pytest.raises(UnknownElsterId, match="E0200002"):
        fields_n(thin)


def test_2025_structure_from_the_pages_covers_the_catalog_and_loads_from_the_repo():
    structure = load_structure("N", 2025)

    assert not structure.provisional
    assert {f.elster_id for f in FIELDS_2025} <= {f.e_kennung for f in structure.fields}
    art = structure.get("E0204401")
    assert art.free_text and "Büromaterial" in art.options


def test_tool_output_loads_as_structure():
    page = (
        '<h1>Seite</h1><div data-node-type="Line">'
        '<label for="a_fields(xE0100001)">Eins</label><input name="fields[xE0100001]">'
    )
    text = json.dumps(epf.build_structure([("1.htm", page)], "N", 2026))

    structure = parse_structure(text)

    assert structure.fields == (StructureField("E0100001", "Seite", (), "", "Eins"),)
    assert not structure.provisional


def test_structure_files_are_there_for_every_year_of_the_catalog():
    assert {p.name for p in DIRECTORY.glob("*.json")} == {f"n-{year}.json" for year in FORMS}


def test_parse_rejects_other_schema_and_doubled_e_kennung():
    data = json.loads((DIRECTORY / "n-2025.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="Schema"):
        parse_structure(json.dumps({**data, "schema": 2}))
    with pytest.raises(ValueError, match="doppelt"):
        parse_structure(json.dumps({**data, "fields": data["fields"] * 2}))


# --- strenge Vorjahres-Zuordnung (nach Vorbild Kohlebau) ------------------------------------


def next_year(*changes: tuple[int, Mapping[str, object]]) -> dict[int, tuple[FormField, ...]]:
    """2025 plus ein synthetisches 2026 mit denselben Feldern, einzelne Felder geändert."""
    fields = list(FIELDS_2025)
    for index, change in changes:
        fields[index] = replace(fields[index], **change)
    return {2025: FIELDS_2025, 2026: tuple(fields)}


def test_the_real_catalog_is_consistent_and_a_copy_of_the_year_passes():
    assert check_previous_years(FORMS) == []
    assert check_previous_years(next_year()) == []


def test_years_without_a_previous_year_are_not_checked():
    assert check_previous_years({2025: FIELDS_2025, 2027: ()}) == []


def test_changed_e_kennung_needs_an_explicit_assignment():
    problems = check_previous_years(next_year((0, {"elster_id": "E0200999"})))

    assert len(problems) == 1
    assert "E0200999 gibt es 2025 nicht" in problems[0]


def test_changed_e_kennung_with_previous_or_new_passes():
    renamed = {"elster_id": "E0200999", "previous": "E0200002"}
    assert check_previous_years(next_year((0, renamed))) == []
    assert check_previous_years(next_year((0, {**renamed, "previous": NEW_FIELD}))) == []


def test_previous_must_exist_in_the_previous_year():
    problems = check_previous_years(next_year((0, {"previous": "E0999999"})))

    assert len(problems) == 1
    assert "E0999999 gibt es 2025 nicht" in problems[0]


def test_mapping_is_one_to_one():
    # Das neue Feld und E0200201 beanspruchen beide E0200201 des Vorjahrs.
    claim = {"elster_id": "E0200999", "previous": "E0200201"}
    problems = check_previous_years(next_year((0, claim)))

    assert len(problems) == 1
    assert "verweist wie E0200999 auf E0200201" in problems[0]


def test_options_and_free_text_load_and_default_to_none():
    text = json.dumps(
        {
            "schema": 1,
            "form": "N",
            "year": 2025,
            "provisional": False,
            "fields": [
                {
                    "e_kennung": "E0100001",
                    "page": "",
                    "headings": [],
                    "line": "1",
                    "label": "A",
                    "options": ["x", "y"],
                    "free_text": True,
                },
                {"e_kennung": "E0100002", "page": "", "headings": [], "line": "2", "label": "B"},
            ],
        }
    )

    art, other = parse_structure(text).fields

    assert (art.options, art.free_text) == (("x", "y"), True)
    assert (other.options, other.free_text) == ((), False)
