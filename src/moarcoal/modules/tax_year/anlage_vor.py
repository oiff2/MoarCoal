"""Felder der Anlage Vorsorgeaufwand (VOR) je Steuerjahr und die Zuordnung der Werte zu ihnen.

Der Katalog nimmt die Felder 2025 mit E-Kennung auf (Quelle: der Katalog des Vorgängerprojekts
Kohlebau, `regeln/2025/anlagen.yaml`: E-Kennung, Zeile, Bezeichnung, Richtung; keine Beträge).
Berechnet werden die Felder „laut Nr. … der Lohnsteuerbescheinigung“, deren Pfad die Einlese-Regel
der Arbeit kennt: Nr. 22 a/b, 23 a/b, 24 b, 24 c und 27. Nr. 24 a, 25 und 26 rechnet sie wie
Anlage N Nr. 17/18: Kennt die Einlese-Regel jeden Pfad der Bescheinigung, ist die Nr. nicht
bescheinigt und das Feld 0 € (Begründung im Rechenweg, Arbeit); sonst noch nicht berechenbar. Alle
übrigen Felder kommen mit dem Modul Vorsorge; bisher Z. 8 (Beiträge zu Basisrentenverträgen,
laut den Anbieterbescheinigungen, Wert `provision.basic_pension`), Z. 23 bis 25 (private Kranken-
und Pflege-Pflichtversicherung, laut den Beitragsbescheinigungen: Beiträge und Erstattungen, Werte
`provision.*`) und Z. 27 (über die Basisabsicherung hinausgehende Beiträge abzüglich erstatteter,
laut den Jahresbeiträgen), Z. 44 bis 46 (Weitere sonstige Vorsorgeaufwendungen: Jahresbeiträge
je Steuerlicher Bedeutung als Einzelangaben je Vertrag, je Einzelangabe aufgerundet) sowie Z. 14
und 15 (Erstattungen der gesetzlichen Versicherung, dieselben
Bescheinigungen). Z. 12 ist 0 € mit Begründung, wo Z. 11 (Nr. 25) 0 € ist, sonst noch nicht
berechenbar. Ein Feld ohne Berechnung hat keinen Wert („wird noch
nicht berechnet“), nie 0. Die Werte sind gerundet, wie das Feld es verlangt: Arbeitgeberanteile,
Zuschüsse und Erstattungen mindern den Abzug und runden wie Einnahmen ab, Beiträge wie Ausgaben auf.
"""

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.field_catalog import (
    FromValue,
    ItemsOfValue,
    SumOfRounded,
    ZeroIfSourceZero,
)
from moarcoal.modules.tax_year.fields import (
    Computed,
    Direction,
    FieldMeaning,
    Itemized,
    Rounding,
)
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

PROVISION_HEALTH_BASIC = ValueKey("provision.private_health_basic")
PROVISION_CARE = ValueKey("provision.private_care")
PROVISION_REFUNDS = ValueKey("provision.private_refunds")
PROVISION_HEALTH_EXTRA = ValueKey("provision.private_health_extra")
PROVISION_UNEMPLOYMENT = ValueKey("provision.unemployment_contributions")
PROVISION_DISABILITY = ValueKey("provision.disability_contributions")
PROVISION_ACCIDENT_LIABILITY_RISK = ValueKey("provision.accident_liability_risk_contributions")
PROVISION_BASIC_PENSION = ValueKey("provision.basic_pension")

PROVISION_STATUTORY_REFUNDS = ValueKey("provision.statutory_refunds")
PROVISION_STATUTORY_REFUNDS_NO_SICK_PAY = ValueKey("provision.statutory_refunds_no_sick_pay")

PROVISION_KEYS = (  # die Werte von Vorsorge, aus denen VOR rechnet
    PROVISION_HEALTH_BASIC,
    PROVISION_CARE,
    PROVISION_REFUNDS,
    PROVISION_HEALTH_EXTRA,
    PROVISION_UNEMPLOYMENT,
    PROVISION_DISABILITY,
    PROVISION_ACCIDENT_LIABILITY_RISK,
    PROVISION_STATUTORY_REFUNDS,
    PROVISION_STATUTORY_REFUNDS_NO_SICK_PAY,
    PROVISION_BASIC_PENSION,
)

VOR_EMPLOYEE_PENSION = ValueKey("tax_year.vor_employee_pension")  # Nr. 23 a/b, Zeile 4
VOR_EMPLOYER_PENSION = ValueKey("tax_year.vor_employer_pension")  # Nr. 22 a/b, Zeile 9
VOR_SUBSIDY_PRIVATE_HEALTH = ValueKey("tax_year.vor_subsidy_private_health")  # Nr. 24 b, Zeile 35
VOR_SUBSIDY_CARE = ValueKey("tax_year.vor_subsidy_care")  # Nr. 24 c, Zeile 36
VOR_UNEMPLOYMENT = ValueKey("tax_year.vor_unemployment")  # Nr. 27, Zeile 43
VOR_SUBSIDY_PUBLIC_HEALTH = ValueKey("tax_year.vor_subsidy_public_health")  # Nr. 24 a, Zeile 34
VOR_EMPLOYEE_HEALTH = ValueKey("tax_year.vor_employee_health")  # Nr. 25, Zeile 11
VOR_EMPLOYEE_CARE = ValueKey("tax_year.vor_employee_care")  # Nr. 26, Zeile 13
VOR_NO_SICK_PAY = ValueKey("tax_year.vor_no_sick_pay")  # Zeile 12
VOR_STATUTORY_REFUNDS = ValueKey("tax_year.vor_statutory_refunds")  # Zeile 14
VOR_STATUTORY_REFUNDS_NO_SICK_PAY = ValueKey("tax_year.vor_statutory_refunds_no_sick_pay")  # Z. 15
VOR_BASIC_PENSION = ValueKey("tax_year.vor_basic_pension")  # Zeile 8
VOR_PRIVATE_HEALTH = ValueKey("tax_year.vor_private_health")  # Zeile 23
VOR_PRIVATE_CARE = ValueKey("tax_year.vor_private_care")  # Zeile 24
VOR_PRIVATE_REFUNDS = ValueKey("tax_year.vor_private_refunds")  # Zeile 25
VOR_PRIVATE_EXTRA = ValueKey("tax_year.vor_private_extra")  # Zeile 27
VOR_UNEMPLOYMENT_CONTRIBUTIONS = ValueKey("tax_year.vor_unemployment_contributions")  # Zeile 44
VOR_DISABILITY = ValueKey("tax_year.vor_disability")  # Zeile 45
VOR_ACCIDENT_LIABILITY_RISK = ValueKey("tax_year.vor_accident_liability_risk")  # Zeile 46


def _zero_if_nr_25_is_zero() -> FieldMeaning:
    """Z. 12 (in Z. 11 enthaltene Beiträge ohne Krankengeldanspruch): 0 €, wo Z. 11 (Nr. 25) 0 €
    ist, denn nichts in Z. 11 gibt auch nichts darin Enthaltenes; sonst noch nicht berechenbar."""
    compute = ZeroIfSourceZero(
        WORK_EMPLOYEE_HEALTH,
        "Arbeitnehmerbeitrag laut Nr. 25",
        "in Zeile 11 steht nichts, also ist auch nichts darin enthalten",
    )
    kind = Computed(Unit.EUR, Rounding.WHOLE_EUROS, compute, Direction.EXPENSE)
    return FieldMeaning("E2001405", kind, VOR_NO_SICK_PAY)


def _computed(
    elster_id: str, key: ValueKey, direction: Direction, source: ValueKey, label: str
) -> FieldMeaning:
    kind = Computed(Unit.EUR, Rounding.WHOLE_EUROS, FromValue(source, label), direction)
    return FieldMeaning(elster_id, kind, key)


def _itemized(
    ids: tuple[str, str, str], key: ValueKey, source: ValueKey, label: str
) -> FieldMeaning:
    """Eine Gruppe mit Einzelangaben (Ausgaben): Bezeichnung, Betrag, Summe; die Einzelposten sind
    die des Werts `source`, je Einzelangabe aufgerundet."""
    label_id, amount_id, total_id = ids
    total = Computed(
        Unit.EUR, Rounding.WHOLE_EUROS, SumOfRounded(ItemsOfValue(source, label)), Direction.EXPENSE
    )
    return FieldMeaning(total_id, Itemized(label_id, amount_id, total), key)


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
        "E2000701",
        VOR_BASIC_PENSION,
        EXPENSE,
        PROVISION_BASIC_PENSION,
        "Beiträge laut Anbieterbescheinigungen",
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
    _zero_if_nr_25_is_zero(),
    _computed(
        "E2001605",
        VOR_STATUTORY_REFUNDS,
        INCOME,
        PROVISION_STATUTORY_REFUNDS,
        "Erstattungen laut Beitragsbescheinigungen",
    ),
    _computed(
        "E2001705",
        VOR_STATUTORY_REFUNDS_NO_SICK_PAY,
        INCOME,
        PROVISION_STATUTORY_REFUNDS_NO_SICK_PAY,
        "Erstattungen laut Beitragsbescheinigungen",
    ),
    _computed(
        "E2001505",
        VOR_EMPLOYEE_CARE,
        EXPENSE,
        WORK_EMPLOYEE_CARE,
        "Arbeitnehmerbeitrag laut Nr. 26",
    ),
    _computed(
        "E2003104",
        VOR_PRIVATE_HEALTH,
        EXPENSE,
        PROVISION_HEALTH_BASIC,
        "Beiträge laut Beitragsbescheinigungen",
    ),
    _computed(
        "E2003202",
        VOR_PRIVATE_CARE,
        EXPENSE,
        PROVISION_CARE,
        "Beiträge laut Beitragsbescheinigungen",
    ),
    _computed(
        "E2003302",
        VOR_PRIVATE_REFUNDS,
        INCOME,
        PROVISION_REFUNDS,
        "Erstattungen laut Beitragsbescheinigungen",
    ),
    _computed(
        "E2003502",
        VOR_PRIVATE_EXTRA,
        EXPENSE,
        PROVISION_HEALTH_EXTRA,
        "Jahresbeiträge abzüglich Erstattungen",
    ),
    _itemized(
        ("E2001401", "E2001402", "E2001403"),
        VOR_UNEMPLOYMENT_CONTRIBUTIONS,
        PROVISION_UNEMPLOYMENT,
        "Jahresbeiträge Arbeitslosigkeit",
    ),
    _itemized(
        ("E2001501", "E2001502", "E2001503"),
        VOR_DISABILITY,
        PROVISION_DISABILITY,
        "Jahresbeiträge Berufsunfähigkeit",
    ),
    _itemized(
        ("E2001801", "E2001802", "E2001803"),
        VOR_ACCIDENT_LIABILITY_RISK,
        PROVISION_ACCIDENT_LIABILITY_RISK,
        "Jahresbeiträge Unfall/Haftpflicht/Risiko",
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
