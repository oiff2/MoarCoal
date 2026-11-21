"""Tests: Katalog der Anlage VOR 2025 (Struktur aus Kohlebau, Werte aus Arbeit)."""

from moarcoal.modules.tax_year.anlage_vor import (
    FIELDS_2025,
    STRUCTURES,
    VOR_EMPLOYEE_CARE,
    VOR_EMPLOYEE_HEALTH,
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_SUBSIDY_CARE,
    VOR_SUBSIDY_PRIVATE_HEALTH,
    VOR_SUBSIDY_PUBLIC_HEALTH,
    VOR_UNEMPLOYMENT,
)
from moarcoal.modules.tax_year.fields import Direction, Rounding
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.values.model import Unit

COMPUTED = {
    "E2000401": (VOR_EMPLOYEE_PENSION, "4", Direction.EXPENSE),  # Nr. 23 a/b
    "E2000801": (VOR_EMPLOYER_PENSION, "9", Direction.INCOME),  # Nr. 22 a/b
    "E2003807": (VOR_SUBSIDY_PRIVATE_HEALTH, "35", Direction.INCOME),  # Nr. 24 b
    "E2003907": (VOR_SUBSIDY_CARE, "36", Direction.INCOME),  # Nr. 24 c
    "E2004403": (VOR_UNEMPLOYMENT, "43", Direction.EXPENSE),  # Nr. 27
    "E2003705": (VOR_SUBSIDY_PUBLIC_HEALTH, "34", Direction.INCOME),  # Nr. 24 a
    "E2001203": (VOR_EMPLOYEE_HEALTH, "11", Direction.EXPENSE),  # Nr. 25
    "E2001505": (VOR_EMPLOYEE_CARE, "13", Direction.EXPENSE),  # Nr. 26
}


def test_vor_is_registered_with_its_stored_structure() -> None:
    (vor,) = [a for a in ANLAGEN if a.form == "VOR"]
    assert vor.structures[2025].form == "VOR" and not vor.structures[2025].provisional


def test_every_catalog_field_is_in_the_structure_and_ids_are_unique() -> None:
    ids = [f.elster_id for f in FIELDS_2025]
    assert len(ids) == len(set(ids)) == len(STRUCTURES[2025].fields)
    assert all(f.unit is Unit.EUR and f.rounding is Rounding.WHOLE_EUROS for f in FIELDS_2025)


def test_every_field_laut_nr_of_the_certificate_is_computed() -> None:
    computed = {f.elster_id: f for f in FIELDS_2025 if f.computed}

    assert set(computed) == set(COMPUTED)
    for elster_id, (key, line, direction) in COMPUTED.items():
        field = computed[elster_id]
        assert (field.key, field.form_line, field.direction) == (key, line, direction)
        assert "Lohnsteuerbescheinigung" in field.label


def test_no_vor_field_laut_lohnsteuerbescheinigung_is_left_open() -> None:
    """Nr. 24 a, 25 und 26 rechnen wie Nr. 17/18: 0 € mit Begründung oder noch nicht berechenbar."""
    open_fields = {
        f.elster_id for f in FIELDS_2025 if not f.computed and "Lohnsteuerbescheinigung" in f.label
    }
    assert open_fields == set()


def test_pages_follow_mein_elster() -> None:
    pages = form_pages(STRUCTURES[2025], FIELDS_2025)
    assert [p.slug for p in pages] == ["1", "2", "3", "5", "7"]
