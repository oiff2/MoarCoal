"""Ausgewiesene Werte der Lohnsteuerbescheinigung: genau wie eingelesen, nie geraten."""

from dataclasses import dataclass

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
SUBSIDY_PUBLIC_HEALTH = ValueKey("work.subsidy_public_health")
EMPLOYEE_HEALTH = ValueKey("work.employee_health_insurance")
EMPLOYEE_CARE = ValueKey("work.employee_care_insurance")


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


def _not_certified(
    calculation: Calculation, number: str, key: str, label: str, reason: str
) -> Amount:
    """Der Posten laut Nr. `number` (17, 18, 24 a, 25, 26): deren Pfad kam in keiner Bescheinigung
    vor. Kennt die Einlese-Regel jeden Pfad der Datei, nennt die Bescheinigung sie nicht, und es
    sind 0 €, begründet mit `reason` (im Rechenweg); sonst ist offen, ob ein unbekannter Pfad sie
    trägt (noch nicht berechenbar)."""
    certificate = _certificate(calculation)
    _reading_is_complete(calculation, certificate, READER_VERSION, number)
    zero = Amount.eur_cents(0)
    place = f"Nr. {number} nicht bescheinigt"
    calculation.item(label, zero, DocumentLocator(certificate.document, Source.READ_IN, key, place))
    calculation.decide(f"Nr. {number} ist nicht bescheinigt: {reason}")
    return calculation.step(f"{label} laut Lohnsteuerbescheinigung", zero)


_NO_EMPLOYER_BENEFIT = "der Arbeitgeber hat dafür nichts geleistet"  # Nr. 17 und 18


@dataclass(frozen=True)
class CertificateLine:
    """Eine Zeile der Lohnsteuerbescheinigung, genau einmal beschrieben (Code: `CertificateLine`).

    `field` ist die Angabe im Eintrag (`WageTaxCertificate`) und bei einer nicht bescheinigten
    Zeile der Feldschlüssel der Fundstelle. Mit `reason` ist die Zeile eine, die in keiner
    Bescheinigung vorkam (Nr. 17, 18, 24 a, 25, 26): ohne unbekannte Pfade 0 € mit dieser
    Begründung; ohne `reason` wird die Angabe gelesen. `since` ist die Fassung der Einlese-Regel,
    ab der sie gelesen wird; `open_b`: Nr. xx b könnte einen eigenen, unbekannten Pfad haben.
    Beschreibung, Kurzname und Zeile der Übersicht ergeben sich aus Bezeichnung und Nr., wenn sie
    nicht ausdrücklich stehen.
    """

    key: ValueKey
    field: str
    label: str
    number: str = ""
    unit: Unit = Unit.EUR
    reason: str = ""
    since: int = 1
    open_b: bool = False
    description: str = ""
    short_label: str = ""
    overview: str = ""

    @property
    def description_text(self) -> str:
        return (
            self.description or f"{self.label} laut Nr. {self.number} der Lohnsteuerbescheinigung"
        )

    @property
    def short_text(self) -> str:
        return self.short_label or f"{self.label} (Nr. {self.number})"

    @property
    def overview_label(self) -> str:
        return self.overview or self.short_text

    def compute(self, calculation: Calculation) -> Amount:
        if self.reason:
            return _not_certified(calculation, self.number, self.field, self.label, self.reason)
        return _certified(
            calculation,
            self.field,
            self.label,
            self.unit,
            since=self.since,
            open_number=self.number if self.open_b else "",
        )


# Reihenfolge wie im Wertekatalog und in der Übersicht der Seite Arbeit
CERTIFICATE_LINES: tuple[CertificateLine, ...] = (
    CertificateLine(
        TAX_CLASS,
        "tax_class",
        "Steuerklasse",
        unit=Unit.TAX_CLASS,
        description="Steuerklasse laut Lohnsteuerbescheinigung",
        short_label="Steuerklasse",
    ),
    CertificateLine(
        GROSS_WAGES,
        "gross_wages_cents",
        "Bruttoarbeitslohn",
        description="Bruttoarbeitslohn laut Lohnsteuerbescheinigung",
        short_label="Bruttoarbeitslohn",
    ),
    CertificateLine(
        INCOME_TAX_WITHHELD,
        "income_tax_cents",
        "Lohnsteuer",
        description="Einbehaltene Lohnsteuer laut Lohnsteuerbescheinigung",
        short_label="Einbehaltene Lohnsteuer",
        overview="Lohnsteuer",
    ),
    CertificateLine(
        SOLI_WITHHELD,
        "soli_cents",
        "Solidaritätszuschlag",
        description="Einbehaltener Solidaritätszuschlag laut Lohnsteuerbescheinigung",
        short_label="Einbehaltener Solidaritätszuschlag",
        overview="Solidaritätszuschlag",
    ),
    CertificateLine(
        BENEFITS_TAX_FREE,
        "employer_benefits_tax_free",
        "Arbeitgeberleistungen, steuerfrei",
        "17",
        reason=_NO_EMPLOYER_BENEFIT,
        description=(
            "Arbeitgeberleistungen laut Nr. 17 der Lohnsteuerbescheinigung (steuerfrei ersetzt)"
        ),
        short_label="Arbeitgeberleistungen, steuerfrei ersetzt (Nr. 17)",
        overview="Arbeitgeberleistungen steuerfrei (Nr. 17)",
    ),
    CertificateLine(
        BENEFITS_FLAT_TAXED,
        "employer_benefits_flat_taxed",
        "Arbeitgeberleistungen, pauschal besteuert",
        "18",
        reason=_NO_EMPLOYER_BENEFIT,
        description=(
            "Arbeitgeberleistungen laut Nr. 18 der Lohnsteuerbescheinigung (pauschal besteuert)"
        ),
        overview="Arbeitgeberleistungen pauschal besteuert (Nr. 18)",
    ),
    CertificateLine(
        SUBSIDY_PUBLIC_HEALTH,
        "subsidy_public_health",
        "Zuschuss zur gesetzlichen Krankenversicherung",
        "24 a",
        reason="kein Zuschuss zur gesetzlichen Krankenversicherung",
        short_label="Zuschuss gesetzliche Krankenversicherung (Nr. 24 a)",
    ),
    CertificateLine(
        EMPLOYEE_HEALTH,
        "employee_health_insurance",
        "Beiträge zur gesetzlichen Krankenversicherung",
        "25",
        reason="keine Beiträge zur gesetzlichen Krankenversicherung",
        short_label="Beiträge gesetzliche Krankenversicherung (Nr. 25)",
    ),
    CertificateLine(
        EMPLOYEE_CARE,
        "employee_care_insurance",
        "Beiträge zur sozialen Pflegeversicherung",
        "26",
        reason="keine Beiträge zur sozialen Pflegeversicherung",
        short_label="Beiträge soziale Pflegeversicherung (Nr. 26)",
    ),
    CertificateLine(
        EMPLOYER_PENSION,
        "employer_pension_cents",
        "Arbeitgeberanteil Rentenversicherung",
        "22 a/b",
        since=VORSORGE_SINCE,
        open_b=True,
    ),
    CertificateLine(
        EMPLOYEE_PENSION,
        "employee_pension_cents",
        "Arbeitnehmeranteil Rentenversicherung",
        "23 a/b",
        since=VORSORGE_SINCE,
        open_b=True,
    ),
    CertificateLine(
        SUBSIDY_PRIVATE_HEALTH,
        "subsidy_private_health_cents",
        "Zuschuss private Krankenversicherung",
        "24 b",
        since=VORSORGE_SINCE,
    ),
    CertificateLine(
        SUBSIDY_CARE,
        "subsidy_care_cents",
        "Zuschuss gesetzliche Pflegeversicherung",
        "24 c",
        since=VORSORGE_SINCE,
    ),
    CertificateLine(
        UNEMPLOYMENT,
        "unemployment_cents",
        "Arbeitnehmerbeitrag Arbeitslosenversicherung",
        "27",
        since=VORSORGE_SINCE,
    ),
)


VALUES: tuple[ValueDefinition, ...] = tuple(
    ValueDefinition(
        CatalogEntry(line.key, line.description_text, line.short_text, line.unit, TimeKind.PERIOD),
        line.compute,
    )
    for line in CERTIFICATE_LINES
)
