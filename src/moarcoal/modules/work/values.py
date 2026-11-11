"""Ausgewiesene Werte des Moduls Arbeit: die erfassten Angaben, ohne Steuerrechnung.

Alle Einzelposten sind Nutzereingaben (Belegstand angenommen). Arbeitstage und einfache Entfernung
gelten je erster Tätigkeitsstätte (Bezugsobjekt); die Arbeitsmittel eines Jahres ergeben einen Wert.
"""

from decimal import Decimal

from moarcoal.modules.work.entries import FirstWorkplace, WorkEquipment
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import (
    Amount,
    Period,
    Subject,
    TimeRef,
    Unit,
    UserInputLocator,
    ValueKey,
)

WORKDAYS = ValueKey("work.workdays")
DISTANCE_KM = ValueKey("work.distance_km")
EQUIPMENT = ValueKey("work.equipment")


def _year(calculation: Calculation) -> int:
    time = calculation.time
    year = time.calendar_year if isinstance(time, Period) else None
    if year is None:
        calculation.not_yet("Der Zeitraum ist kein Kalenderjahr")
    return year


def _workplace(calculation: Calculation) -> FirstWorkplace:
    year = _year(calculation)
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


def compute_equipment(calculation: Calculation) -> Amount:
    year = _year(calculation)
    purchases = [e for e in calculation.own.all(WorkEquipment) if e.year == year]
    total = Amount.of(Decimal(0), Unit.EUR)
    if not purchases:
        calculation.decide(f"Für {year} sind keine Arbeitsmittel erfasst; der Betrag ist 0")
        return calculation.step("Summe der Arbeitsmittel", total)
    for purchase in purchases:
        amount = Amount.eur_cents(purchase.input.amount_cents)
        calculation.item(purchase.input.description, amount, UserInputLocator(purchase.address))
        total = Amount(total.value + amount.value, Unit.EUR)
    return calculation.step("Summe der Arbeitsmittel", total)


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
)
