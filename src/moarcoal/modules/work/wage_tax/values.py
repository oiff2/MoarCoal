"""Ausgewiesene Werte der Lohnsteuerbescheinigung: genau wie eingelesen, nie geraten."""

from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, DocumentLocator, Source, Unit, ValueKey

TAX_CLASS = ValueKey("work.tax_class")
GROSS_WAGES = ValueKey("work.gross_wages")
INCOME_TAX_WITHHELD = ValueKey("work.income_tax_withheld")
SOLI_WITHHELD = ValueKey("work.soli_withheld")


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


def _certified(calculation: Calculation, key: str, label: str, unit: Unit) -> Amount:
    """Die bescheinigte Angabe `key`, genau wie eingelesen; fehlt sie in der Datei: noch nicht."""
    certificate = _certificate(calculation)
    number = getattr(certificate, key)
    if number is None:
        calculation.not_yet(f"Die Lohnsteuerbescheinigung {certificate.year} nennt {label} nicht")
    amount = Amount.of(number, unit) if unit is not Unit.EUR else Amount.eur_cents(number)
    place = certificate.places[key.removesuffix("_cents")]
    calculation.item(
        label, amount, DocumentLocator(certificate.document, Source.READ_IN, key, place)
    )
    return calculation.step(f"{label} laut Lohnsteuerbescheinigung", amount)


def compute_tax_class(calculation: Calculation) -> Amount:
    return _certified(calculation, "tax_class", "Steuerklasse", Unit.TAX_CLASS)


def compute_gross_wages(calculation: Calculation) -> Amount:
    return _certified(calculation, "gross_wages_cents", "Bruttoarbeitslohn", Unit.EUR)


def compute_income_tax(calculation: Calculation) -> Amount:
    return _certified(calculation, "income_tax_cents", "Lohnsteuer", Unit.EUR)


def compute_soli(calculation: Calculation) -> Amount:
    return _certified(calculation, "soli_cents", "Solidaritätszuschlag", Unit.EUR)


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
)
