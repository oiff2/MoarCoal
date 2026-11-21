"""Felder der Anlage Vorsorgeaufwand (VOR) je Steuerjahr und die Zuordnung der Werte zu ihnen.

Der Katalog nimmt die Felder 2025 mit E-Kennung auf (Quelle: der Katalog des Vorgängerprojekts
Kohlebau, `regeln/2025/anlagen.yaml`: E-Kennung, Zeile, Bezeichnung, Richtung; keine Beträge).
Berechnet werden die Felder „laut Nr. … der Lohnsteuerbescheinigung“, deren Pfad die Einlese-Regel
der Arbeit kennt: Nr. 22 a/b, 23 a/b, 24 b, 24 c und 27. Nr. 24 a, 25 und 26 hat der Katalog,
berechnet sie aber nicht (Pfad in der Bescheinigung unbekannt); alle übrigen Felder kommen mit dem
Modul Vorsorge. Ein Feld ohne Berechnung hat keinen Wert („wird noch nicht berechnet“), nie 0. Die
Werte sind gerundet, wie das Feld es verlangt: Arbeitgeberanteile, Zuschüsse und Erstattungen
mindern den Abzug und runden wie Einnahmen ab, Beiträge wie Ausgaben auf.
"""

from collections.abc import Mapping
from functools import partial

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.field_catalog import (
    Compute,
    catalog_field,
    work_total,
)
from moarcoal.modules.tax_year.field_catalog import values_for as define_values
from moarcoal.modules.tax_year.fields import Direction, FormField, Forms, Rounding
from moarcoal.modules.tax_year.structure import FormStructure, load_structure
from moarcoal.values.catalog import ValueDefinition
from moarcoal.values.model import Unit, ValueKey

FORM = "VOR"  # Anlage Vorsorgeaufwand

WORK_EMPLOYER_PENSION = ValueKey("work.employer_pension_share")
WORK_EMPLOYEE_PENSION = ValueKey("work.employee_pension_share")
WORK_SUBSIDY_PRIVATE_HEALTH = ValueKey("work.subsidy_private_health")
WORK_SUBSIDY_CARE = ValueKey("work.subsidy_care")
WORK_UNEMPLOYMENT = ValueKey("work.employee_unemployment_insurance")

WORK_KEYS = (  # die Werte von Arbeit, aus denen VOR rechnet
    WORK_EMPLOYER_PENSION,
    WORK_EMPLOYEE_PENSION,
    WORK_SUBSIDY_PRIVATE_HEALTH,
    WORK_SUBSIDY_CARE,
    WORK_UNEMPLOYMENT,
)

VOR_EMPLOYEE_PENSION = ValueKey("tax_year.vor_employee_pension")  # Nr. 23 a/b, Zeile 4
VOR_EMPLOYER_PENSION = ValueKey("tax_year.vor_employer_pension")  # Nr. 22 a/b, Zeile 9
VOR_SUBSIDY_PRIVATE_HEALTH = ValueKey("tax_year.vor_subsidy_private_health")  # Nr. 24 b, Zeile 35
VOR_SUBSIDY_CARE = ValueKey("tax_year.vor_subsidy_care")  # Nr. 24 c, Zeile 36
VOR_UNEMPLOYMENT = ValueKey("tax_year.vor_unemployment")  # Nr. 27, Zeile 43

INCOME, EXPENSE = Direction.INCOME, Direction.EXPENSE

# E-Kennung, Richtung, Schlüssel (nur bei den Feldern, die MoarCoal berechnet)
FIELD_TABLE: tuple[tuple[str, Direction, ValueKey | None], ...] = (
    ("E2000401", EXPENSE, VOR_EMPLOYEE_PENSION),
    ("E2000701", EXPENSE, None),
    ("E2000801", INCOME, VOR_EMPLOYER_PENSION),
    ("E2001203", EXPENSE, None),
    ("E2001405", EXPENSE, None),
    ("E2001505", EXPENSE, None),
    ("E2001605", INCOME, None),
    ("E2001705", INCOME, None),
    ("E2003104", EXPENSE, None),
    ("E2003202", EXPENSE, None),
    ("E2003302", INCOME, None),
    ("E2003502", EXPENSE, None),
    ("E2003705", INCOME, None),
    ("E2003807", INCOME, VOR_SUBSIDY_PRIVATE_HEALTH),
    ("E2003907", INCOME, VOR_SUBSIDY_CARE),
    ("E2004403", EXPENSE, VOR_UNEMPLOYMENT),
    ("E2001803", EXPENSE, None),
)


def fields_vor(structure: FormStructure) -> tuple[FormField, ...]:
    """Die Felder der Anlage VOR: Bedeutung aus der Tabelle, Bezeichnung, Nr. aus der Struktur."""
    return tuple(
        catalog_field(
            FORM,
            structure,
            key or ValueKey(f"tax_year.vor_{elster_id.lower()}"),
            elster_id,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            direction,
            computed=key is not None,
        )
        for elster_id, direction, key in FIELD_TABLE
    )


STRUCTURES: Mapping[int, FormStructure] = {2025: load_structure(FORM, 2025)}
FIELDS_2025 = fields_vor(STRUCTURES[2025])

FORMS: Forms = {2025: FIELDS_2025}

_COMPUTE: dict[ValueKey, Compute] = {
    VOR_EMPLOYEE_PENSION: partial(
        work_total, source=WORK_EMPLOYEE_PENSION, label="Arbeitnehmeranteil laut Nr. 23 a/b"
    ),
    VOR_EMPLOYER_PENSION: partial(
        work_total, source=WORK_EMPLOYER_PENSION, label="Arbeitgeberanteil laut Nr. 22 a/b"
    ),
    VOR_SUBSIDY_PRIVATE_HEALTH: partial(
        work_total, source=WORK_SUBSIDY_PRIVATE_HEALTH, label="Zuschuss laut Nr. 24 b"
    ),
    VOR_SUBSIDY_CARE: partial(work_total, source=WORK_SUBSIDY_CARE, label="Zuschuss laut Nr. 24 c"),
    VOR_UNEMPLOYMENT: partial(
        work_total, source=WORK_UNEMPLOYMENT, label="Arbeitnehmerbeitrag laut Nr. 27"
    ),
}


def values_for(forms: Forms) -> tuple[ValueDefinition, ...]:
    return define_values(FORM, forms, _COMPUTE)


ANLAGE_VOR = Anlage(FORM, FORMS, STRUCTURES, values_for)
