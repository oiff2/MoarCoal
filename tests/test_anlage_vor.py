"""Tests: Katalog der Anlage VOR 2025 (Struktur aus Kohlebau, Werte aus Arbeit)."""

from moarcoal.modules.tax_year.anlage_vor import (
    FIELDS_2025,
    STRUCTURES,
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_SUBSIDY_CARE,
    VOR_SUBSIDY_PRIVATE_HEALTH,
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
}


def test_vor_is_registered_with_its_stored_structure() -> None:
    (vor,) = [a for a in ANLAGEN if a.form == "VOR"]
    assert vor.structures[2025].form == "VOR" and not vor.structures[2025].provisional


def test_every_catalog_field_is_in_the_structure_and_ids_are_unique() -> None:
    ids = [f.elster_id for f in FIELDS_2025]
    assert len(ids) == len(set(ids)) == len(STRUCTURES[2025].fields)
    assert all(f.unit is Unit.EUR and f.rounding is Rounding.WHOLE_EUROS for f in FIELDS_2025)


def test_only_the_fields_laut_nr_of_the_certificate_are_computed() -> None:
    computed = {f.elster_id: f for f in FIELDS_2025 if f.computed}

    assert set(computed) == set(COMPUTED)
    for elster_id, (key, line, direction) in COMPUTED.items():
        field = computed[elster_id]
        assert (field.key, field.form_line, field.direction) == (key, line, direction)
        assert "Lohnsteuerbescheinigung" in field.label


def test_nr_24_a_25_and_26_are_in_the_catalog_but_not_computed_yet() -> None:
    """Der Pfad dieser Nummern in der Bescheinigung ist unbekannt: kein Wert, nie 0."""
    pending = {
        f.elster_id: f
        for f in FIELDS_2025
        if not f.computed and "Lohnsteuerbescheinigung" in f.label
    }
    assert set(pending) == {"E2001203", "E2001505", "E2003705"}


def test_pages_follow_mein_elster() -> None:
    pages = form_pages(STRUCTURES[2025], FIELDS_2025)
    assert [p.slug for p in pages] == ["1", "2", "3", "5", "7"]
