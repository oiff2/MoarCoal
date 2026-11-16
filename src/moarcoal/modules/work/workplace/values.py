"""Ausgewiesene Werte der ersten Tätigkeitsstätte und der Arbeitsmittel (Nutzereingaben).

Alle Einzelposten sind Nutzereingaben (Belegstand angenommen). Arbeitstage und einfache Entfernung
gelten je erster Tätigkeitsstätte (Bezugsobjekt); die Arbeitsmittel eines Jahres ergeben einen Wert.
"""

from decimal import Decimal

from moarcoal.modules.work.workplace.entries import FirstWorkplace, WorkEquipment
from moarcoal.registration import ModuleState
from moarcoal.values.calculation import Calculation, ValueSource
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.findings import Finding, FindingKind, Severity
from moarcoal.values.model import (
    Amount,
    Period,
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
WORKDAYS_PER_WEEK = ValueKey("work.workdays_per_week")
ABSENCE_DAYS = ValueKey("work.absence_days")
CAR_DISTANCE_KM = ValueKey("work.car_distance_km")
HOMEOFFICE_DAYS = ValueKey("work.homeoffice_days")


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


def _optional_input(calculation: Calculation, attribute: str, label: str, unit: Unit) -> Amount:
    """Eine freiwillige Angabe der ersten Tätigkeitsstätte; fehlt sie, ist der Wert noch nicht
    berechenbar (nie 0)."""
    entry = _workplace(calculation)
    number = getattr(entry, attribute)
    if number is None:
        calculation.not_yet(f"{label} für {calculation.year} nicht erfasst")
    amount = Amount.of(number, unit)
    calculation.item(label, amount, UserInputLocator(entry.address))
    return calculation.step(f"{label} laut Eingabe", amount)


def compute_workdays_per_week(calculation: Calculation) -> Amount:
    return _optional_input(calculation, "workdays_per_week", "Arbeitstage je Woche", Unit.DAYS)


def compute_absence_days(calculation: Calculation) -> Amount:
    return _optional_input(calculation, "absence_days", "Urlaubs- und Krankheitstage", Unit.DAYS)


def compute_homeoffice_days(calculation: Calculation) -> Amount:
    return _optional_input(calculation, "homeoffice_days", "Homeoffice-Tage", Unit.DAYS)


def compute_car_distance(calculation: Calculation) -> Amount:
    return _optional_input(calculation, "car_distance_km", "Mit dem Pkw gefahrene km", Unit.KM)


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


EQUIPMENT_GAP = "work.equipment_gap"

FINDING_KINDS = (FindingKind(EQUIPMENT_GAP, "Arbeitsmittel im Vorjahr, im Steuerjahr keine"),)


def equipment_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Hinweis: Arbeitsmittel im Vorjahr, im Steuerjahr keine (vergessen?)."""
    if _purchases(state, year) or not _purchases(state, year - 1):
        return []
    text = (
        f"Für {year - 1} sind Arbeitsmittel erfasst, für {year} keine; "
        "der Wert ist 0. Fehlt eine Anschaffung?"
    )
    ref = ValueRef(EQUIPMENT, state.user, Period.year(year), None)
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
            WORKDAYS_PER_WEEK,
            "Arbeitstage je Woche an einer ersten Tätigkeitsstätte",
            Unit.DAYS,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_workdays_per_week,
        _workplace_subjects,
    ),
    ValueDefinition(
        CatalogEntry(
            ABSENCE_DAYS,
            "Urlaubs- und Krankheitstage bei einer ersten Tätigkeitsstätte im Steuerjahr",
            Unit.DAYS,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_absence_days,
        _workplace_subjects,
    ),
    ValueDefinition(
        CatalogEntry(
            HOMEOFFICE_DAYS,
            "Homeoffice-Tage bei einer ersten Tätigkeitsstätte im Steuerjahr",
            Unit.DAYS,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_homeoffice_days,
        _workplace_subjects,
    ),
    ValueDefinition(
        CatalogEntry(
            CAR_DISTANCE_KM,
            "Mit dem eigenen Pkw gefahrene km zu einer ersten Tätigkeitsstätte im Steuerjahr",
            Unit.KM,
            TimeKind.PERIOD,
            has_subject=True,
        ),
        compute_car_distance,
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
