"""Tests: Katalog der Anlage VOR 2025 (Struktur aus Kohlebau, Werte aus Arbeit)."""

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_vor import (
    ANLAGE_VOR,
    VOR_ACCIDENT_LIABILITY_RISK,
    VOR_DISABILITY,
    VOR_EMPLOYEE_CARE,
    VOR_EMPLOYEE_HEALTH,
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_NO_SICK_PAY,
    VOR_PRIVATE_CARE,
    VOR_PRIVATE_EXTRA,
    VOR_PRIVATE_HEALTH,
    VOR_PRIVATE_REFUNDS,
    VOR_STATUTORY_REFUNDS,
    VOR_STATUTORY_REFUNDS_NO_SICK_PAY,
    VOR_SUBSIDY_CARE,
    VOR_SUBSIDY_PRIVATE_HEALTH,
    VOR_SUBSIDY_PUBLIC_HEALTH,
    VOR_UNEMPLOYMENT,
    VOR_UNEMPLOYMENT_CONTRIBUTIONS,
    WORK_EMPLOYEE_HEALTH,
)
from moarcoal.modules.tax_year.field_catalog import FromValue, ItemsOfValue, SumOfRounded
from moarcoal.modules.tax_year.fields import (
    Computed,
    Direction,
    Itemized,
    NotComputed,
    Rounding,
)
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.values.engine import ForeignResult
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    NotApplicable,
    NotYetComputable,
    Period,
    Unit,
)
from moarcoal.values.testing import evaluate, fixed, not_applicable, not_yet

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
    "E2001605": (
        VOR_STATUTORY_REFUNDS,
        "14",
        Direction.INCOME,
        "provision.statutory_refunds",
    ),
    "E2001705": (
        VOR_STATUTORY_REFUNDS_NO_SICK_PAY,
        "15",
        Direction.INCOME,
        "provision.statutory_refunds_no_sick_pay",
    ),
}
# Z. 44 bis 46: Einzelangaben (Bezeichnung, Betrag, Summe), Einzelposten des Werts von Vorsorge
ITEMIZED = {
    "E2001403": ("E2001401", "E2001402", VOR_UNEMPLOYMENT_CONTRIBUTIONS, "44"),
    "E2001503": ("E2001501", "E2001502", VOR_DISABILITY, "45"),
    "E2001803": ("E2001801", "E2001802", VOR_ACCIDENT_LIABILITY_RISK, "46"),
}
ITEMIZED_SOURCES = {
    "E2001403": "provision.unemployment_contributions",
    "E2001503": "provision.disability_contributions",
    "E2001803": "provision.accident_liability_risk_contributions",
}
# Z. 12 rechnet aus Nr. 25 (`ZeroIfSourceZero`, eigener Test unten)
OWN_RULE = {"E2001405"}


def test_vor_is_registered_with_its_stored_structure() -> None:
    (vor,) = [a for a in ANLAGEN if a.form == "VOR"]
    assert vor.structures[2025].form == "VOR" and not vor.structures[2025].provisional


def test_the_catalog_names_the_computed_fields_and_the_rest_of_the_structure_comes_along() -> None:
    ids = [f.elster_id for f in FIELDS]
    # alle der Struktur, einmal; Bezeichnung und Betrag der Einzelangaben gehen in der Summe auf
    absorbed = {i for label, amount, _, _ in ITEMIZED.values() for i in (label, amount)}
    assert ids == [f.e_kennung for f in STRUCTURE.fields if f.e_kennung not in absorbed]
    computed_count = len(COMPUTED) + len(FROM_PROVISION) + len(OWN_RULE) + len(ITEMIZED)
    assert len(ANLAGE_VOR.catalogs[2025]) == computed_count < len(FIELDS)
    assert all(
        isinstance(f.kind, NotComputed)
        for f in FIELDS
        if f.elster_id not in COMPUTED | FROM_PROVISION | ITEMIZED | dict.fromkeys(OWN_RULE)
    )


def test_every_field_laut_nr_of_the_certificate_is_computed() -> None:
    computed = {f.elster_id: f for f in FIELDS if f.computed}

    assert set(computed) == set(COMPUTED) | set(FROM_PROVISION) | set(ITEMIZED) | OWN_RULE
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


def test_lines_44_to_46_are_itemized_expenses_rounded_up_per_item() -> None:
    fields = {f.elster_id: f for f in FIELDS}

    for sum_id, (label_id, amount_id, key, line) in ITEMIZED.items():
        field = fields[sum_id]
        itemized = field.kind
        assert isinstance(itemized, Itemized)
        assert (itemized.label_id, itemized.amount_id) == (label_id, amount_id)
        assert (field.key, field.form_line) == (key, line)
        total = itemized.total
        assert (total.unit, total.rounding) == (Unit.EUR, Rounding.WHOLE_EUROS)
        assert total.direction is Direction.EXPENSE
        assert isinstance(total.compute, SumOfRounded)
        collect = total.compute.collect
        assert isinstance(collect, ItemsOfValue) and collect.source == ITEMIZED_SOURCES[sum_id]


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


# --- Z. 12: 0 € mit Begründung, wo Nr. 25 der Lohnsteuerbescheinigung 0 € ist -----------------

YEAR = Period.year(2025)
NR_25 = (WORK_EMPLOYEE_HEALTH, None, YEAR)


def line_12(source: ForeignResult) -> ExposedValue | NotYetComputable | NotApplicable:
    result = evaluate([TAX_YEAR], foreign={NR_25: source}).get(VOR_NO_SICK_PAY, "anna", YEAR)
    assert isinstance(result, ExposedValue | NotYetComputable | NotApplicable), result
    return result


def test_line_12_is_zero_with_reason_when_nr_25_is_zero() -> None:
    result = line_12(fixed(Amount.eur_cents(0)))

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.eur_cents(0)
    decisions = [s.text for s in result.workings.steps if s.kind == "decision"]
    assert len(decisions) == 1 and "ist 0 €" in decisions[0] and "Nr. 25" in decisions[0]


def test_line_12_is_not_yet_computable_when_nr_25_is_above_zero() -> None:
    result = line_12(fixed(Amount.eur_cents(123_456)))

    assert isinstance(result, NotYetComputable)
    assert "Nr. 25" in result.reason and "nicht 0 €" in result.reason


def test_line_12_is_not_yet_computable_when_nr_25_is() -> None:
    result = line_12(not_yet("keine Lohnsteuerbescheinigung"))

    assert isinstance(result, NotYetComputable)
    assert "keine Lohnsteuerbescheinigung" in result.reason


def test_line_12_does_not_apply_when_nr_25_does() -> None:
    assert isinstance(line_12(not_applicable("nicht anzuwenden")), NotApplicable)


def test_line_12_is_a_computed_field_of_the_vor_catalog() -> None:
    (field,) = [f for f in FIELDS if f.elster_id == "E2001405"]
    kind = field.kind
    assert isinstance(kind, Computed)
    assert (field.key, field.form_line, kind.direction) == (
        VOR_NO_SICK_PAY,
        "12",
        Direction.EXPENSE,
    )
    assert kind.rounding is Rounding.WHOLE_EUROS
