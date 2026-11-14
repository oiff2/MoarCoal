"""Ausgewiesene Werte des Moduls Arbeit: die erfassten Angaben, ohne Steuerrechnung.

Alle Einzelposten sind Nutzereingaben (Belegstand angenommen). Arbeitstage und einfache Entfernung
gelten je erster Tätigkeitsstätte (Bezugsobjekt); die Arbeitsmittel eines Jahres ergeben einen Wert.
"""

from decimal import Decimal

from moarcoal.modules.work.entries import FirstWorkplace, WageTaxCertificate, WorkEquipment
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import Calculation, ValueSource
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.findings import Finding, FindingKind, Severity
from moarcoal.values.model import (
    Amount,
    DocumentLocator,
    Period,
    Source,
    Subject,
    TimeRef,
    Unit,
    UserInputLocator,
    ValueKey,
    ValueRef,
)

WORKDAYS = ValueKey("work.workdays")
DISTANCE_KM = ValueKey("work.distance_km")
EQUIPMENT = ValueKey("work.equipment")
TAX_CLASS = ValueKey("work.tax_class")
GROSS_WAGES = ValueKey("work.gross_wages")
INCOME_TAX_WITHHELD = ValueKey("work.income_tax_withheld")
SOLI_WITHHELD = ValueKey("work.soli_withheld")


def _workplace(calculation: Calculation) -> FirstWorkplace:
    year = calculation.year
    subject = calculation.subject
    entry = None if subject is None else calculation.own.get(subject.address)
    if not isinstance(entry, FirstWorkplace) or entry.year != year:
        calculation.not_yet(f"Keine erste Tätigkeitsstätte für {year}")
    return entry


def _workplace_subjects(state: ModuleState, time: TimeRef) -> list[Subject]:
    year = time.calendar_year if isinstance(time, Period) else None
    return [Subject(e.address) for e in state.all(FirstWorkplace) if e.year == year]


def compute_workdays(calculation: Calculation) -> Amount:
    entry = _workplace(calculation)
    days = Amount.of(entry.workdays, Unit.DAYS)
    calculation.item("Arbeitstage", days, UserInputLocator(entry.address))
    return calculation.step("Arbeitstage laut Eingabe", days)


def compute_distance(calculation: Calculation) -> Amount:
    entry = _workplace(calculation)
    distance = Amount.of(entry.distance_km, Unit.KM)
    calculation.item("Einfache Entfernung", distance, UserInputLocator(entry.address))
    return calculation.step("Einfache Entfernung laut Eingabe", distance)


def _purchases(state: ModuleState, year: int) -> list[WorkEquipment]:
    return [e for e in state.all(WorkEquipment) if e.year == year]


def compute_equipment(calculation: Calculation) -> Amount:
    """Summe der Anschaffungen; ohne Anschaffung 0, mit Hinweis, wenn das Vorjahr welche hatte."""
    year = calculation.year
    purchases = _purchases(calculation.own, year)
    zero = Amount.of(Decimal(0), Unit.EUR)
    if not purchases:
        previous = year - 1
        before = (
            f"im Vorjahr {previous} schon (siehe Hinweis)"
            if _purchases(calculation.own, previous)
            else f"auch im Vorjahr {previous} keine"
        )
        calculation.decide(f"Für {year} sind keine Arbeitsmittel erfasst, {before}")
        return calculation.step("Keine Arbeitsmittel", zero)
    total = Amount.of(Decimal(0), Unit.EUR)
    for purchase in purchases:
        amount = Amount.eur_cents(purchase.input.amount_cents)
        calculation.item(purchase.input.description, amount, UserInputLocator(purchase.address))
        total = Amount(total.value + amount.value, Unit.EUR)
    return calculation.step("Summe der Arbeitsmittel", total)


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


EQUIPMENT_GAP = "work.equipment_gap"

FINDING_KINDS = (FindingKind(EQUIPMENT_GAP, "Arbeitsmittel im Vorjahr, im Steuerjahr keine"),)


def work_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Hinweis, wenn das Vorjahr Arbeitsmittel hatte und das Steuerjahr keine (vergessen?)."""
    if _purchases(state, year) or not _purchases(state, year - 1):
        return []
    ref = ValueRef(EQUIPMENT, state.user, Period.year(year), None)
    text = (
        f"Für {year - 1} sind Arbeitsmittel erfasst, für {year} keine; "
        "der Wert ist 0. Fehlt eine Anschaffung?"
    )
    return [Finding(EQUIPMENT_GAP, Severity.NOTE, ref, text, href="/arbeit")]


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            WORKDAYS,
            "Arbeitstage an einer ersten Tätigkeitsstätte im Steuerjahr",
            Unit.DAYS,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_workdays,
        _workplace_subjects,
    ),
    ValueDefinition(
        CatalogEntry(
            DISTANCE_KM,
            "Einfache Entfernung zu einer ersten Tätigkeitsstätte im Steuerjahr",
            Unit.KM,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_distance,
        _workplace_subjects,
    ),
    ValueDefinition(
        CatalogEntry(
            EQUIPMENT,
            "Summe der Arbeitsmittel, die im Steuerjahr angeschafft wurden",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_equipment,
    ),
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
