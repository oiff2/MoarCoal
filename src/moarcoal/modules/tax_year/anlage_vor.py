"""Felder der Anlage Vorsorgeaufwand (VOR) je Steuerjahr und die Zuordnung der Werte zu ihnen.

Der Katalog nimmt die Felder 2025 mit E-Kennung auf (Quelle: der Katalog des Vorgängerprojekts
Kohlebau, `regeln/2025/anlagen.yaml`: E-Kennung, Zeile, Bezeichnung, Richtung; keine Beträge).
Berechnet werden die Felder „laut Nr. … der Lohnsteuerbescheinigung“, deren Pfad die Einlese-Regel
der Arbeit kennt: Nr. 22 a/b, 23 a/b, 24 b, 24 c und 27. Nr. 24 a, 25 und 26 rechnet sie wie
Anlage N Nr. 17/18: Kennt die Einlese-Regel jeden Pfad der Bescheinigung, ist die Nr. nicht
bescheinigt und das Feld 0 € (Begründung im Rechenweg, Arbeit); sonst noch nicht berechenbar. Alle
übrigen Felder kommen mit dem Modul Vorsorge. Ein Feld ohne Berechnung hat keinen Wert („wird noch
nicht berechnet“), nie 0. Die Werte sind gerundet, wie das Feld es verlangt: Arbeitgeberanteile,
Zuschüsse und Erstattungen mindern den Abzug und runden wie Einnahmen ab, Beiträge wie Ausgaben auf.
"""

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.field_catalog import FromValue
from moarcoal.modules.tax_year.fields import Computed, Direction, FieldMeaning, Rounding
from moarcoal.values.model import Unit, ValueKey

FORM = "VOR"  # Anlage Vorsorgeaufwand

WORK_EMPLOYER_PENSION = ValueKey("work.employer_pension_share")
WORK_EMPLOYEE_PENSION = ValueKey("work.employee_pension_share")
WORK_SUBSIDY_PRIVATE_HEALTH = ValueKey("work.subsidy_private_health")
WORK_SUBSIDY_CARE = ValueKey("work.subsidy_care")
WORK_UNEMPLOYMENT = ValueKey("work.employee_unemployment_insurance")
WORK_SUBSIDY_PUBLIC_HEALTH = ValueKey("work.subsidy_public_health")
WORK_EMPLOYEE_HEALTH = ValueKey("work.employee_health_insurance")
WORK_EMPLOYEE_CARE = ValueKey("work.employee_care_insurance")

WORK_KEYS = (  # die Werte von Arbeit, aus denen VOR rechnet
    WORK_EMPLOYER_PENSION,
    WORK_EMPLOYEE_PENSION,
    WORK_SUBSIDY_PRIVATE_HEALTH,
    WORK_SUBSIDY_CARE,
    WORK_UNEMPLOYMENT,
    WORK_SUBSIDY_PUBLIC_HEALTH,
    WORK_EMPLOYEE_HEALTH,
    WORK_EMPLOYEE_CARE,
)

VOR_EMPLOYEE_PENSION = ValueKey("tax_year.vor_employee_pension")  # Nr. 23 a/b, Zeile 4
VOR_EMPLOYER_PENSION = ValueKey("tax_year.vor_employer_pension")  # Nr. 22 a/b, Zeile 9
VOR_SUBSIDY_PRIVATE_HEALTH = ValueKey("tax_year.vor_subsidy_private_health")  # Nr. 24 b, Zeile 35
VOR_SUBSIDY_CARE = ValueKey("tax_year.vor_subsidy_care")  # Nr. 24 c, Zeile 36
VOR_UNEMPLOYMENT = ValueKey("tax_year.vor_unemployment")  # Nr. 27, Zeile 43
VOR_SUBSIDY_PUBLIC_HEALTH = ValueKey("tax_year.vor_subsidy_public_health")  # Nr. 24 a, Zeile 34
VOR_EMPLOYEE_HEALTH = ValueKey("tax_year.vor_employee_health")  # Nr. 25, Zeile 11
VOR_EMPLOYEE_CARE = ValueKey("tax_year.vor_employee_care")  # Nr. 26, Zeile 13


def _computed(
    elster_id: str, key: ValueKey, direction: Direction, source: ValueKey, label: str
) -> FieldMeaning:
    kind = Computed(Unit.EUR, Rounding.WHOLE_EUROS, FromValue(source, label), direction)
    return FieldMeaning(elster_id, kind, key)


INCOME, EXPENSE = Direction.INCOME, Direction.EXPENSE

# Nur die Felder, die MoarCoal berechnet; die übrigen der Struktur kommen als `NotComputed` dazu
# (`all_structure_fields`). Quelle von E-Kennung, Zeile, Bezeichnung: die Struktur.
CATALOG_2025 = (
    _computed(
        "E2000401",
        VOR_EMPLOYEE_PENSION,
        EXPENSE,
        WORK_EMPLOYEE_PENSION,
        "Arbeitnehmeranteil laut Nr. 23 a/b",
    ),
    _computed(
        "E2000801",
        VOR_EMPLOYER_PENSION,
        INCOME,
        WORK_EMPLOYER_PENSION,
        "Arbeitgeberanteil laut Nr. 22 a/b",
    ),
    _computed(
        "E2001203",
        VOR_EMPLOYEE_HEALTH,
        EXPENSE,
        WORK_EMPLOYEE_HEALTH,
        "Arbeitnehmerbeitrag laut Nr. 25",
    ),
    _computed(
        "E2001505",
        VOR_EMPLOYEE_CARE,
        EXPENSE,
        WORK_EMPLOYEE_CARE,
        "Arbeitnehmerbeitrag laut Nr. 26",
    ),
    _computed(
        "E2003705",
        VOR_SUBSIDY_PUBLIC_HEALTH,
        INCOME,
        WORK_SUBSIDY_PUBLIC_HEALTH,
        "Zuschuss laut Nr. 24 a",
    ),
    _computed(
        "E2003807",
        VOR_SUBSIDY_PRIVATE_HEALTH,
        INCOME,
        WORK_SUBSIDY_PRIVATE_HEALTH,
        "Zuschuss laut Nr. 24 b",
    ),
    _computed("E2003907", VOR_SUBSIDY_CARE, INCOME, WORK_SUBSIDY_CARE, "Zuschuss laut Nr. 24 c"),
    _computed(
        "E2004403", VOR_UNEMPLOYMENT, EXPENSE, WORK_UNEMPLOYMENT, "Arbeitnehmerbeitrag laut Nr. 27"
    ),
)

ANLAGE_VOR = Anlage(FORM, {2025: CATALOG_2025}, all_structure_fields=True)
