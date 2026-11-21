"""Ausgewiesene Werte der Lohnsteuerbescheinigung: genau wie eingelesen, nie geraten."""

from collections.abc import Callable

from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.modules.work.wage_tax.reading import READER_VERSION
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, DocumentLocator, Source, Unit, ValueKey

TAX_CLASS = ValueKey("work.tax_class")
GROSS_WAGES = ValueKey("work.gross_wages")
INCOME_TAX_WITHHELD = ValueKey("work.income_tax_withheld")
SOLI_WITHHELD = ValueKey("work.soli_withheld")
BENEFITS_TAX_FREE = ValueKey("work.employer_benefits_tax_free")
BENEFITS_FLAT_TAXED = ValueKey("work.employer_benefits_flat_taxed")
VORSORGE_SINCE = 3  # Fassung der Einlese-Regel, ab der Nr. 22 bis 24 und 27 gelesen werden
EMPLOYER_PENSION = ValueKey("work.employer_pension_share")
EMPLOYEE_PENSION = ValueKey("work.employee_pension_share")
SUBSIDY_PRIVATE_HEALTH = ValueKey("work.subsidy_private_health")
SUBSIDY_CARE = ValueKey("work.subsidy_care")
UNEMPLOYMENT = ValueKey("work.employee_unemployment_insurance")


def _certificate(calculation: Calculation) -> WageTaxCertificate:
    """Die Lohnsteuerbescheinigung des Jahrs; ohne sie oder bei mehreren: noch nicht berechenbar."""
    year = calculation.year
    found = [c for c in calculation.own.all(WageTaxCertificate) if c.year == year]
    if not found:
        calculation.not_yet(f"Für {year} ist keine Lohnsteuerbescheinigung aufgenommen")
    if len(found) > 1:
        calculation.not_yet(
            f"Für {year} sind {len(found)} Lohnsteuerbescheinigungen aufgenommen; "
            "eine ist die einzige, die gilt"
        )
    return found[0]


def _reading_is_complete(
    calculation: Calculation, certificate: WageTaxCertificate, since: int, number: str
) -> None:
    """Sonst noch nicht berechenbar: die Einlesung ist älter als `since`, oder die Datei hat Pfade,
    die die Einlese-Regel nicht kennt, und `number` (leer: keine Nr. betroffen) könnte darunter
    sein."""
    if certificate.reader_version < since:
        calculation.not_yet(
            f"Die Lohnsteuerbescheinigung {certificate.year} ist mit einer älteren Einlese-Regel "
            "eingelesen; sie wird beim nächsten Start neu eingelesen"
        )
    if number and certificate.unrecognized:
        calculation.not_yet(
            f"Die Lohnsteuerbescheinigung {certificate.year} enthält Angaben, die MoarCoal nicht "
            f"kennt ({', '.join(certificate.unrecognized)}); "
            f"ob Nr. {number} darunter ist, ist offen"
        )


def _certified(
    calculation: Calculation,
    key: str,
    label: str,
    unit: Unit,
    *,
    since: int = 1,
    open_number: str = "",
) -> Amount:
    """Die bescheinigte Angabe `key`, genau wie eingelesen; fehlt sie in der Datei: noch nicht.

    `since` ist die Fassung der Einlese-Regel, ab der die Angabe gelesen wird; eine ältere Einlesung
    sagt nichts darüber, ob die Datei sie nennt. `open_number` (z. B. „22 a/b“) nennt die Nr.,
    deren Betrag ein Pfad der Datei tragen könnte, den die Einlese-Regel nicht kennt (Nr. 22 b,
    23 b): dann ist offen, ob der Betrag vollständig ist.
    """
    certificate = _certificate(calculation)
    _reading_is_complete(calculation, certificate, since, open_number)
    number = getattr(certificate, key)
    if number is None:
        calculation.not_yet(f"Die Lohnsteuerbescheinigung {certificate.year} nennt {label} nicht")
    amount = Amount.of(number, unit) if unit is not Unit.EUR else Amount.eur_cents(number)
    place = certificate.places[key.removesuffix("_cents")]
    calculation.item(
        label, amount, DocumentLocator(certificate.document, Source.READ_IN, key, place)
    )
    return calculation.step(f"{label} laut Lohnsteuerbescheinigung", amount)


def _not_certified(calculation: Calculation, number: str, key: str, label: str) -> Amount:
    """Arbeitgeberleistungen laut Nr. `number`: deren Pfad kam in keiner Bescheinigung vor. Kennt
    die Einlese-Regel jeden Pfad der Datei, nennt die Bescheinigung sie nicht, und es sind 0 €;
    sonst ist offen, ob ein unbekannter Pfad sie trägt (noch nicht berechenbar)."""
    certificate = _certificate(calculation)
    _reading_is_complete(calculation, certificate, READER_VERSION, number)
    zero = Amount.eur_cents(0)
    place = f"Nr. {number} nicht bescheinigt"
    calculation.item(label, zero, DocumentLocator(certificate.document, Source.READ_IN, key, place))
    calculation.decide(
        f"Nr. {number} ist nicht bescheinigt: der Arbeitgeber hat dafür nichts geleistet"
    )
    return calculation.step(f"{label} laut Lohnsteuerbescheinigung", zero)


def compute_benefits_tax_free(calculation: Calculation) -> Amount:
    return _not_certified(
        calculation, "17", "employer_benefits_tax_free", "Arbeitgeberleistungen, steuerfrei"
    )


def compute_benefits_flat_taxed(calculation: Calculation) -> Amount:
    return _not_certified(
        calculation,
        "18",
        "employer_benefits_flat_taxed",
        "Arbeitgeberleistungen, pauschal besteuert",
    )


def compute_tax_class(calculation: Calculation) -> Amount:
    return _certified(calculation, "tax_class", "Steuerklasse", Unit.TAX_CLASS)


def compute_gross_wages(calculation: Calculation) -> Amount:
    return _certified(calculation, "gross_wages_cents", "Bruttoarbeitslohn", Unit.EUR)


def compute_income_tax(calculation: Calculation) -> Amount:
    return _certified(calculation, "income_tax_cents", "Lohnsteuer", Unit.EUR)


def compute_soli(calculation: Calculation) -> Amount:
    return _certified(calculation, "soli_cents", "Solidaritätszuschlag", Unit.EUR)


def _vorsorge(
    key: str, label: str, number: str, *, open_b: bool
) -> Callable[[Calculation], Amount]:
    """Der Betrag laut Nr. `number`; `open_b`: Nr. xx b könnte einen eigenen, unbekannten Pfad
    haben (22 und 23 nennen a und b zusammen)."""

    def compute(calculation: Calculation) -> Amount:
        return _certified(
            calculation,
            key,
            label,
            Unit.EUR,
            since=VORSORGE_SINCE,
            open_number=number if open_b else "",
        )

    return compute


# Schlüssel, Angabe im Eintrag, Bezeichnung, Nr.; ob die Nr. einen b-Teil mit unbekanntem Pfad hat
VORSORGE_VALUES: tuple[tuple[ValueKey, str, str, str, bool], ...] = (
    (
        EMPLOYER_PENSION,
        "employer_pension_cents",
        "Arbeitgeberanteil Rentenversicherung",
        "22 a/b",
        True,
    ),
    (
        EMPLOYEE_PENSION,
        "employee_pension_cents",
        "Arbeitnehmeranteil Rentenversicherung",
        "23 a/b",
        True,
    ),
    (
        SUBSIDY_PRIVATE_HEALTH,
        "subsidy_private_health_cents",
        "Zuschuss private Krankenversicherung",
        "24 b",
        False,
    ),
    (SUBSIDY_CARE, "subsidy_care_cents", "Zuschuss gesetzliche Pflegeversicherung", "24 c", False),
    (
        UNEMPLOYMENT,
        "unemployment_cents",
        "Arbeitnehmerbeitrag Arbeitslosenversicherung",
        "27",
        False,
    ),
)


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            TAX_CLASS,
            "Steuerklasse laut Lohnsteuerbescheinigung",
            Unit.TAX_CLASS,
            TimeKind.PERIOD,
        ),
        compute_tax_class,
    ),
    ValueDefinition(
        CatalogEntry(
            GROSS_WAGES,
            "Bruttoarbeitslohn laut Lohnsteuerbescheinigung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_gross_wages,
    ),
    ValueDefinition(
        CatalogEntry(
            INCOME_TAX_WITHHELD,
            "Einbehaltene Lohnsteuer laut Lohnsteuerbescheinigung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_income_tax,
    ),
    ValueDefinition(
        CatalogEntry(
            SOLI_WITHHELD,
            "Einbehaltener Solidaritätszuschlag laut Lohnsteuerbescheinigung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_soli,
    ),
    ValueDefinition(
        CatalogEntry(
            BENEFITS_TAX_FREE,
            "Arbeitgeberleistungen laut Nr. 17 der Lohnsteuerbescheinigung (steuerfrei ersetzt)",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_benefits_tax_free,
    ),
    ValueDefinition(
        CatalogEntry(
            BENEFITS_FLAT_TAXED,
            "Arbeitgeberleistungen laut Nr. 18 der Lohnsteuerbescheinigung (pauschal besteuert)",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_benefits_flat_taxed,
    ),
    *(
        ValueDefinition(
            CatalogEntry(
                key,
                f"{label} laut Nr. {number} der Lohnsteuerbescheinigung",
                Unit.EUR,
                TimeKind.PERIOD,
            ),
            _vorsorge(field, label, number, open_b=open_b),
        )
        for key, field, label, number, open_b in VORSORGE_VALUES
    ),
)
