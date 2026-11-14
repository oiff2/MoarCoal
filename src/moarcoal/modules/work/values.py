"""Ausgewiesene Werte des Moduls Arbeit: die erfassten Angaben, ohne Steuerrechnung.

Alle Einzelposten sind Nutzereingaben (Belegstand angenommen). Arbeitstage und einfache Entfernung
gelten je erster Tätigkeitsstätte (Bezugsobjekt); die Arbeitsmittel eines Jahres ergeben einen Wert.
Die Fahrtkosten der Dienstreisen sind die km des Jahrs mal dem km-Satz des Jahrs.
"""

from decimal import Decimal

from moarcoal.modules.work.entries import (
    BusinessTrip,
    FirstWorkplace,
    TripsConfirmation,
    WageTaxCertificate,
    WorkEquipment,
)
from moarcoal.modules.work.trips import (
    KM_RATES,
    current_confirmation,
    format_places,
    km_amount,
    sorted_trips,
)
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
WORKDAYS_PER_WEEK = ValueKey("work.workdays_per_week")
ABSENCE_DAYS = ValueKey("work.absence_days")
CAR_DISTANCE_KM = ValueKey("work.car_distance_km")
TRIP_DAYS = ValueKey("work.trip_days")
TRAVEL_FARE = ValueKey("work.travel_fare")
TRAVEL_TOTAL = ValueKey("work.travel_total")


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


def _trips(state: ModuleState, year: int) -> list[BusinessTrip]:
    return sorted_trips([t for t in state.all(BusinessTrip) if t.year == year])


def _confirmation(state: ModuleState, year: int) -> TripsConfirmation | None:
    confirmations = [c for c in state.all(TripsConfirmation) if c.year == year]
    return current_confirmation(confirmations, _trips(state, year))


def compute_trip_days(calculation: Calculation) -> Amount:
    """Dienstreisetage des Jahrs: je Reise Ende minus Start plus 1, ohne Ende ein Tag.

    Wie bei den Fahrtkosten gilt ohne Reisen nur die Bestätigung als vollständig (dann 0)."""
    year = calculation.year
    trips = _trips(calculation.own, year)
    if not trips and _confirmation(calculation.own, year) is None:
        calculation.not_yet(
            f"Für {year} sind keine Dienstreisen erfasst und nicht als vollständig bestätigt"
        )
    total = 0
    for trip in trips:
        days = ((trip.end or trip.start) - trip.start).days + 1
        label = f"Dienstreise {trip.start:%d.%m.%Y}, {format_places(trip.places)}"
        calculation.item(label, Amount.of(days, Unit.DAYS), UserInputLocator(trip.address))
        total += days
    if not trips:
        calculation.decide(f"Dienstreisen {year} sind als vollständig bestätigt, es gab keine")
    return calculation.step("Summe der Dienstreisetage", Amount.of(total, Unit.DAYS))


def compute_travel_fare(calculation: Calculation) -> Amount:
    """Fahrtkosten mit dem privaten Pkw: erst alle km des Jahrs summieren, dann einmal mal km-Satz.

    Ohne Reisen gilt das nur, wenn der Nutzer die Dienstreisen als vollständig bestätigt hat
    (dann ausdrücklich 0); sonst ist der Wert noch nicht berechenbar.
    """
    year = calculation.year
    trips = _trips(calculation.own, year)
    rate = KM_RATES.get(year)
    if rate is None:
        calculation.not_yet(f"Für {year} ist der km-Satz noch nicht hinterlegt")
    confirmed = _confirmation(calculation.own, year)
    if not trips and confirmed is None:
        calculation.not_yet(
            f"Für {year} sind keine Dienstreisen erfasst und nicht als vollständig bestätigt"
        )
    total_km = 0
    for trip in trips:
        label = f"Dienstreise {trip.start:%d.%m.%Y}, {format_places(trip.places)}"
        calculation.item(
            label, Amount.of(trip.distance_km, Unit.KM), UserInputLocator(trip.address)
        )
        total_km += trip.distance_km
    if not trips:
        calculation.decide(f"Dienstreisen {year} sind als vollständig bestätigt, es gab keine")
    calculation.step("Summe der km", Amount.of(total_km, Unit.KM))
    rate_text = f"{rate:.2f}".replace(".", ",")
    return calculation.step(
        f"{total_km} km × {rate_text} €/km", Amount(km_amount(total_km, rate), Unit.EUR)
    )


def compute_travel_total(calculation: Calculation) -> Amount:
    """Summe der Reisekosten: erfasst sind nur Fahrtkosten, Verpflegung, Übernachtung und
    Nebenkosten rechnet der Arbeitgeber ab."""
    item = calculation.use(TRAVEL_FARE, label="Fahrtkosten")
    if item is None:
        calculation.not_applicable("Fahrtkosten entfallen")
    return calculation.step("Summe der Reisekosten (nur Fahrtkosten erfasst)", item.amount)


EQUIPMENT_GAP = "work.equipment_gap"
TRIPS_TO_FILL = "work.trips_to_fill"

FINDING_KINDS = (
    FindingKind(EQUIPMENT_GAP, "Arbeitsmittel im Vorjahr, im Steuerjahr keine"),
    FindingKind(TRIPS_TO_FILL, "Dienstreisen noch auszufüllen"),
)


def work_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Hinweise: Arbeitsmittel im Vorjahr, im Steuerjahr keine (vergessen?); Dienstreisen offen."""
    found: list[Finding] = []
    period = Period.year(year)
    if not _purchases(state, year) and _purchases(state, year - 1):
        text = (
            f"Für {year - 1} sind Arbeitsmittel erfasst, für {year} keine; "
            "der Wert ist 0. Fehlt eine Anschaffung?"
        )
        ref = ValueRef(EQUIPMENT, state.user, period, None)
        found.append(Finding(EQUIPMENT_GAP, Severity.NOTE, ref, text, href="/arbeit"))
    if _confirmation(state, year) is None:
        text = (
            f"Dienstreisen {year} noch auszufüllen: erfassen und als vollständig bestätigen "
            "(auch wenn es keine gab)."
        )
        ref = ValueRef(TRAVEL_FARE, state.user, period, None)
        href = f"/arbeit/dienstreisen/{year}"
        found.append(Finding(TRIPS_TO_FILL, Severity.NOTE, ref, text, href=href))
    return found


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
            TRIP_DAYS,
            "Tage der Dienstreisen im Steuerjahr",
            Unit.DAYS,
            TimeKind.PERIOD,
        ),
        compute_trip_days,
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
    ValueDefinition(
        CatalogEntry(
            TRAVEL_FARE,
            "Fahrtkosten der Dienstreisen mit dem privaten Pkw im Steuerjahr",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_travel_fare,
    ),
    ValueDefinition(
        CatalogEntry(
            TRAVEL_TOTAL,
            "Summe der Reisekosten der Dienstreisen im Steuerjahr",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        compute_travel_total,
    ),
)
