"""Tests: Katalog der Anlage VOR 2025 (Struktur aus Kohlebau, Werte aus Arbeit)."""

from moarcoal.modules.tax_year.anlage_vor import (
    ANLAGE_VOR,
    VOR_EMPLOYEE_CARE,
    VOR_EMPLOYEE_HEALTH,
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_PRIVATE_CARE,
    VOR_PRIVATE_EXTRA,
    VOR_PRIVATE_HEALTH,
    VOR_PRIVATE_REFUNDS,
    VOR_SUBSIDY_CARE,
    VOR_SUBSIDY_PRIVATE_HEALTH,
    VOR_SUBSIDY_PUBLIC_HEALTH,
    VOR_UNEMPLOYMENT,
)
from moarcoal.modules.tax_year.field_catalog import FromValue
from moarcoal.modules.tax_year.fields import Computed, Direction, NotComputed, Rounding
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.values.model import Unit

FIELDS = ANLAGE_VOR.fields[2025]
STRUCTURE = ANLAGE_VOR.structures[2025]

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
# Felder aus Beitragsbescheinigungen und Jahresbeiträgen des Moduls Vorsorge (Werte `provision.*`)
FROM_PROVISION = {
    "E2003104": (VOR_PRIVATE_HEALTH, "23", Direction.EXPENSE, "provision.private_health_basic"),
    "E2003202": (VOR_PRIVATE_CARE, "24", Direction.EXPENSE, "provision.private_care"),
    "E2003302": (VOR_PRIVATE_REFUNDS, "25", Direction.INCOME, "provision.private_refunds"),
    "E2003502": (VOR_PRIVATE_EXTRA, "27", Direction.EXPENSE, "provision.private_health_extra"),
}


def test_vor_is_registered_with_its_stored_structure() -> None:
    (vor,) = [a for a in ANLAGEN if a.form == "VOR"]
    assert vor.structures[2025].form == "VOR" and not vor.structures[2025].provisional


def test_the_catalog_names_the_computed_fields_and_the_rest_of_the_structure_comes_along() -> None:
    ids = [f.elster_id for f in FIELDS]
    assert ids == [f.e_kennung for f in STRUCTURE.fields]  # alle der Struktur, einmal
    assert len(ANLAGE_VOR.catalogs[2025]) == len(COMPUTED) + len(FROM_PROVISION) < len(FIELDS)
    assert all(
        isinstance(f.kind, NotComputed)
        for f in FIELDS
        if f.elster_id not in COMPUTED | FROM_PROVISION
    )


def test_every_field_laut_nr_of_the_certificate_is_computed() -> None:
    computed = {f.elster_id: f for f in FIELDS if f.computed}

    assert set(computed) == set(COMPUTED) | set(FROM_PROVISION)
    for elster_id, (key, line, direction) in COMPUTED.items():
        field = computed[elster_id]
        kind = field.kind
        assert isinstance(kind, Computed)
        assert (field.key, field.form_line, kind.direction) == (key, line, direction)
        assert (kind.unit, kind.rounding) == (Unit.EUR, Rounding.WHOLE_EUROS)
        assert "Lohnsteuerbescheinigung" in field.label


def test_lines_23_to_25_and_27_are_computed_from_the_values_of_the_provision_module() -> None:
    computed = {f.elster_id: f for f in FIELDS if f.computed}

    for elster_id, (key, line, direction, source) in FROM_PROVISION.items():
        field = computed[elster_id]
        kind = field.kind
        assert isinstance(kind, Computed)
        assert (field.key, field.form_line, kind.direction) == (key, line, direction)
        assert (kind.unit, kind.rounding) == (Unit.EUR, Rounding.WHOLE_EUROS)
        assert isinstance(kind.compute, FromValue) and kind.compute.source == source


def test_no_vor_field_laut_lohnsteuerbescheinigung_is_left_open() -> None:
    """Nr. 24 a, 25 und 26 rechnen wie Nr. 17/18: 0 € mit Begründung oder noch nicht berechenbar."""
    open_fields = {
        f.elster_id for f in FIELDS if not f.computed and "Lohnsteuerbescheinigung" in f.label
    }
    # Zeile 5 (berufsständische Versorgung) nennt Nr. 22 b nur als Abzug; der Beitrag selbst
    # kommt aus dem Modul Vorsorge.
    assert open_fields == {"E2000501"}


def test_pages_follow_mein_elster() -> None:
    pages = form_pages(STRUCTURE, FIELDS)
    assert [p.slug for p in pages] == ["1", "2", "3", "5", "7", "8"]
