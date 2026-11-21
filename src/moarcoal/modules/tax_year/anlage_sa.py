"""Felder der Anlage Sonderausgaben (SA) je Steuerjahr: die Kirchensteuer, aus den
Kirchensteuerzahlungen.

Struktur (`strukturen/sa-2025.json`) aus dem Katalog des Vorgängerprojekts Kohlebau,
`regeln/2025/anlagen.yaml` (E-Kennung, Zeile, Bezeichnung, Richtung; keine Beträge). Die
Einzelangaben
(Art der Leistung E0108003, Betrag E0108004) und die übrigen Sonderausgaben (Spenden u. a.) stehen
dort ohne Zeile oder Bezeichnung und fehlen darum, bis eine gespeicherte Seite sie liefert.

Der Betrag eines Felds ist die Summe der Zahlungen (gezahlt) oder Erstattungen im Jahr der Zahlung,
gerundet wie das Feld es verlangt. Fehlt jede Zahlung, entscheidet die Religionszugehörigkeit laut
Angaben zur Person: ohne Kirchensteuer das ganze Jahr entfällt das Feld, sonst ist es noch nicht
berechenbar, nie 0. Gibt es Zahlungen, zählen sie auch dann (eine Nachzahlung oder Erstattung nach
dem Austritt gehört ins Jahr der Zahlung); eine Richtung ohne Eintrag entfällt dann, denn Mein
ELSTER lässt das Feld leer.
"""

from collections.abc import Mapping
from functools import partial

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment, payments_in_year
from moarcoal.modules.tax_year.field_catalog import Compute, catalog_field, rounded
from moarcoal.modules.tax_year.field_catalog import values_for as define_values
from moarcoal.modules.tax_year.fields import Direction, FormField, Forms, Rounding
from moarcoal.modules.tax_year.structure import FormStructure, load_structure
from moarcoal.personal_details import church_tax_applies
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import ValueDefinition
from moarcoal.values.model import Amount, Unit, UserInputLocator, ValueKey, format_eur

FORM = "SA"  # Anlage Sonderausgaben

SA_PAID = ValueKey("tax_year.sa_church_tax_paid")  # Zeile 4, E0107601
SA_REFUNDED = ValueKey("tax_year.sa_church_tax_refunded")  # Zeile 4, E0107602

# E-Kennung, Richtung, Schlüssel; Erstattete Kirchensteuer mindert den Abzug und rundet wie eine
# Einnahme ab.
FIELD_TABLE: tuple[tuple[str, Direction, ValueKey], ...] = (
    ("E0107601", Direction.EXPENSE, SA_PAID),
    ("E0107602", Direction.INCOME, SA_REFUNDED),
)


def fields_sa(structure: FormStructure) -> tuple[FormField, ...]:
    return tuple(
        catalog_field(
            FORM,
            structure,
            key,
            elster_id,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            direction,
            computed=True,
        )
        for elster_id, direction, key in FIELD_TABLE
    )


STRUCTURES: Mapping[int, FormStructure] = {2025: load_structure(FORM, 2025)}
FIELDS_2025 = fields_sa(STRUCTURES[2025])

FORMS: Forms = {2025: FIELDS_2025}

NO_PAYMENT = "Keine Kirchensteuerzahlung für {year} erfasst (Steuerjahr, Anlage Sonderausgaben)"


def _without_payments(calculation: Calculation, year: int) -> None:
    """Es gibt in diesem Jahr gar keine Zahlung: nach der Religionszugehörigkeit entscheiden."""
    details = calculation.own.personal_details()
    applies = None if details is None else church_tax_applies(details, year)
    if applies is False:
        calculation.not_applicable(
            f"Keine Kirchensteuer {year}: keine kirchensteuerberechtigte Religionsgemeinschaft "
            "laut Angaben zur Person"
        )
    if applies is None:
        calculation.not_yet(
            f"Religionszugehörigkeit {year} fehlt in den Angaben zur Person, und es ist keine "
            "Kirchensteuerzahlung erfasst"
        )
    calculation.not_yet(NO_PAYMENT.format(year=year))


def compute_church_tax(calculation: Calculation, field: FormField, *, refunded: bool) -> Amount:
    year = calculation.year
    in_year = payments_in_year(calculation.own, year)
    if not in_year:
        _without_payments(calculation, year)
    counted: list[ChurchTaxPayment] = [p for p in in_year if p.refunded is refunded]
    word = "erstattet" if refunded else "gezahlt"
    if not counted:
        calculation.not_applicable(f"Unter den Kirchensteuerzahlungen {year} ist nichts {word}")
    total = Amount(Amount.eur_cents(0).value, Unit.EUR)
    for payment in counted:
        amount = Amount.eur_cents(payment.amount_cents)
        label = f"{payment.date:%d.%m.%Y}: {payment.benefit_type}"
        calculation.item(label, amount, UserInputLocator(payment.address))
        total = Amount(total.value + amount.value, Unit.EUR)
    calculation.decide(
        f"{len(counted)} Kirchensteuerzahlung{'en' if len(counted) != 1 else ''} {word} "
        f"im Jahr der Zahlung {year}: {format_eur(round(total.value * 100))}"
    )
    return rounded(calculation, field, calculation.step(f"Summe {word}", total))


_COMPUTE: dict[ValueKey, Compute] = {
    SA_PAID: partial(compute_church_tax, refunded=False),
    SA_REFUNDED: partial(compute_church_tax, refunded=True),
}


def values_for(forms: Forms) -> tuple[ValueDefinition, ...]:
    return define_values(FORM, forms, _COMPUTE)


ANLAGE_SA = Anlage(FORM, FORMS, STRUCTURES, values_for)
