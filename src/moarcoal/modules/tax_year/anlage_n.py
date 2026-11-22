"""Katalog der Anlage N 2025 und die Rechnungen, die nicht einfach einen Wert übernehmen.

Der Katalog enthält alle für 2025 bekannten Felder: jedes mit Betrag ist berechnet (`Computed`),
jedes ohne Betrag nimmt eine Eingabe im Steuerjahr (`TypedInput`). Ein Feld zeigt die erfassten
Angaben wie ELSTER sie verlangt, ohne Steuerrechnung (keine Entfernungspauschale). Die Werte kommen
aus dem Modul Arbeit, das das Steuerjahr nur über ihre Schlüssel kennt. Die Werte der Felder sind
gerundet, wie das Feld es verlangt; der Rundungsschritt steht im Rechenweg, die Werte des Moduls
Arbeit bleiben genau.
"""

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.assessment import (
    BUSINESS_TRAVEL,
    COMMUTE_DAYS,
    COMMUTE_KM,
    GROSS_WAGES,
    INCOME_TAX_WITHHELD,
    MEAL_ALLOWANCE,
    SOLI_WITHHELD,
)
from moarcoal.modules.tax_year.field_catalog import FromValue, rounded
from moarcoal.modules.tax_year.fields import (
    Compute,
    Computed,
    Direction,
    FieldMeaning,
    FormField,
    Rounding,
    TypedInput,
)
from moarcoal.modules.tax_year.structure import FormStructure, load_structure
from moarcoal.values.calculation import Calculation
from moarcoal.values.model import Amount, Unit, ValueKey

FORM = "N"  # Anlage N (Person A)
YES_NO = ("Ja", "Nein")  # Auswahl von Nr. 65; die Struktur nennt für Auswahlfelder ohne Liste keine

WORK_WORKDAYS = ValueKey("work.workdays")
WORK_DISTANCE_KM = ValueKey("work.distance_km")
WORK_EQUIPMENT = ValueKey("work.equipment")
WORK_TAX_CLASS = ValueKey("work.tax_class")
WORK_GROSS_WAGES = ValueKey("work.gross_wages")
WORK_INCOME_TAX = ValueKey("work.income_tax_withheld")
WORK_SOLI = ValueKey("work.soli_withheld")
WORK_WORKDAYS_PER_WEEK = ValueKey("work.workdays_per_week")
WORK_ABSENCE_DAYS = ValueKey("work.absence_days")
WORK_CAR_DISTANCE = ValueKey("work.car_distance_km")
WORK_HOMEOFFICE_DAYS = ValueKey("work.homeoffice_days")
WORK_TRIP_DAYS = ValueKey("work.trip_days")
WORK_TRAVEL_FARE = ValueKey("work.travel_fare")
WORK_TRAVEL_TOTAL = ValueKey("work.travel_total")
WORK_BENEFITS_TAX_FREE = ValueKey("work.employer_benefits_tax_free")
WORK_BENEFITS_FLAT_TAXED = ValueKey("work.employer_benefits_flat_taxed")

N_WORKPLACE_DAYS = ValueKey("tax_year.n_workplace_days")
N_WORKPLACE_DISTANCE = ValueKey("tax_year.n_workplace_distance")
N_WORKDAYS_PER_WEEK = ValueKey("tax_year.n_workdays_per_week")
N_ABSENCE_DAYS = ValueKey("tax_year.n_absence_days")
N_CAR_DISTANCE = ValueKey("tax_year.n_car_distance")
N_EQUIPMENT = ValueKey("tax_year.n_equipment")
N_HOMEOFFICE_DAYS = ValueKey("tax_year.n_homeoffice_days")
N_TAX_CLASS = ValueKey("tax_year.n_tax_class")
N_GROSS_WAGES = ValueKey("tax_year.n_gross_wages")
N_GROSS_WAGES_SINGLE = ValueKey("tax_year.n_gross_wages_single")
N_INCOME_TAX = ValueKey("tax_year.n_income_tax")
N_INCOME_TAX_SINGLE = ValueKey("tax_year.n_income_tax_single")
N_SOLI = ValueKey("tax_year.n_soli")
N_SOLI_SINGLE = ValueKey("tax_year.n_soli_single")
N_TRAVEL_FARE = ValueKey("tax_year.n_travel_fare")
N_TRAVEL_TOTAL = ValueKey("tax_year.n_travel_total")
N_REFUND_TAX_FREE = ValueKey("tax_year.n_refund_tax_free")
N_REFUND_FLAT_TAXED = ValueKey("tax_year.n_refund_flat_taxed")


def _work_value(calculation: Calculation, field: FormField, source: ValueKey, label: str) -> Amount:
    """Übernimmt den Wert je erster Tätigkeitsstätte; mehrere sind noch nicht zugeordnet."""
    year = calculation.year
    subjects = calculation.subjects_of(source)
    if not subjects:
        calculation.not_yet(f"Für {year} ist keine erste Tätigkeitsstätte erfasst")
    if len(subjects) > 1:
        calculation.not_yet(
            f"Für {year} sind {len(subjects)} erste Tätigkeitsstätten erfasst; "
            "die Zuordnung zu den Einträgen der Tabelle in Anlage N ist noch nicht festgelegt"
        )
    item = calculation.use(source, subjects[0], label=label)
    if item is None:
        calculation.not_applicable(f"{label} entfällt")
    amount = calculation.step(f"{label} übernommen", item.amount)
    return rounded(calculation, field, amount)


def compute_workplace_days(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_WORKDAYS, "Arbeitstage")


def compute_workplace_distance(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_DISTANCE_KM, "Einfache Entfernung")


def compute_workdays_per_week(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_WORKDAYS_PER_WEEK, "Arbeitstage je Woche")


def compute_car_distance(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_CAR_DISTANCE, "Mit dem Pkw gefahrene km")


def compute_homeoffice_days(calculation: Calculation, field: FormField) -> Amount:
    """Nr. 58: die Homeoffice-Tage der ersten Tätigkeitsstätte."""
    return _work_value(calculation, field, WORK_HOMEOFFICE_DAYS, "Homeoffice-Tage")


def homeoffice_days(calculation: Calculation) -> Amount:
    """Homeoffice-Tage (Nr. 58) als Summand von Nr. 28."""
    item = calculation.use(N_HOMEOFFICE_DAYS, label="Homeoffice-Tage")
    if item is None:
        calculation.not_applicable("Homeoffice-Tage entfallen")
    return item.amount


def compute_absence_days(calculation: Calculation, field: FormField) -> Amount:
    """Nr. 28 „Urlaubs-, Krankheits-, Heimarbeits- und Dienstreisetage“: Summe aus den Urlaubs-
    und Krankheitstagen der Tätigkeitsstätte, den Homeoffice-Tagen (Nr. 58) und den Tagen der
    Dienstreisen. Fehlt ein Summand, ist das Feld noch nicht berechenbar (nie 0)."""
    absence = _work_value(calculation, field, WORK_ABSENCE_DAYS, "Urlaubs- und Krankheitstage")
    trips = calculation.use(WORK_TRIP_DAYS, label="Dienstreisetage")
    if trips is None:
        calculation.not_applicable("Dienstreisetage entfallen")
    home = homeoffice_days(calculation)
    total = Amount(absence.value + trips.amount.value + home.value, Unit.DAYS)
    return calculation.step(
        f"{absence.value} Urlaubs- und Krankheitstage + {home.value} Homeoffice-Tage "
        f"+ {trips.amount.value} Dienstreisetage",
        total,
    )


# Quelle von E-Kennung, Nr. im Vordruck und Bezeichnung: das Übertragungsprotokoll der Abgabe 2025
# (E-Kennung, Zeile, Bezeichnung; keine Beträge), für Arbeitsmittel die Seite „10 - Aufwendungen
# für Arbeitsmittel“ in Mein ELSTER (Summe, tools/elster_page_fields.py). Der Katalog nimmt alle
# bekannten Felder mit; berechnet werden bisher nur die mit Quelle im Modul Arbeit (`Computed`).
# Die Positionen des EStB (`assessment`) und welche er gerundet druckt, hat der Mensch an einem
# echten EStB zugeordnet (#54).
def _from_value(
    elster_id: str,
    key: ValueKey,
    unit: Unit,
    rounding: Rounding,
    compute: Compute,
    direction: Direction | None = None,
    *,
    assessment: tuple[str, ...] = (),
    printed_rounded: bool = False,
) -> FieldMeaning:
    kind = Computed(unit, rounding, compute, direction, assessment, printed_rounded)
    return FieldMeaning(elster_id, kind, key)


def catalog_2025(structure: FormStructure) -> tuple[FieldMeaning, ...]:
    """Die Bedeutung der Felder der Anlage N 2025; Auswahlen der Eingaben stehen in der Struktur."""
    return (
        _from_value(
            "E0200002",
            N_TAX_CLASS,
            Unit.TAX_CLASS,
            Rounding.NONE,
            FromValue(WORK_TAX_CLASS, "Steuerklasse"),
        ),
        _from_value(
            "E0200201",
            N_GROSS_WAGES,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_GROSS_WAGES, "Bruttoarbeitslohn"),
            Direction.INCOME,
            assessment=(GROSS_WAGES,),
        ),
        _from_value(
            "E0200204",
            N_GROSS_WAGES_SINGLE,
            Unit.EUR,
            Rounding.EURO_CENTS,
            FromValue(WORK_GROSS_WAGES, "Bruttoarbeitslohn"),
        ),
        _from_value(
            "E0200301",
            N_INCOME_TAX,
            Unit.EUR,
            Rounding.EURO_CENTS,
            FromValue(WORK_INCOME_TAX, "Lohnsteuer"),
            assessment=(INCOME_TAX_WITHHELD,),
            printed_rounded=True,
        ),
        _from_value(
            "E0200304",
            N_INCOME_TAX_SINGLE,
            Unit.EUR,
            Rounding.EURO_CENTS,
            FromValue(WORK_INCOME_TAX, "Lohnsteuer"),
        ),
        _from_value(
            "E0200401",
            N_SOLI,
            Unit.EUR,
            Rounding.EURO_CENTS,
            FromValue(WORK_SOLI, "Solidaritätszuschlag"),
            assessment=(SOLI_WITHHELD,),
        ),
        _from_value(
            "E0200404",
            N_SOLI_SINGLE,
            Unit.EUR,
            Rounding.EURO_CENTS,
            FromValue(WORK_SOLI, "Solidaritätszuschlag"),
        ),
        FieldMeaning("E0203003", TypedInput(structure.get("E0203003").options)),
        FieldMeaning("E0203501", TypedInput()),
        FieldMeaning("E0203101", TypedInput(day_range=True)),
        _from_value(
            "E0203508", N_WORKDAYS_PER_WEEK, Unit.DAYS, Rounding.NONE, compute_workdays_per_week
        ),
        _from_value("E0203509", N_ABSENCE_DAYS, Unit.DAYS, Rounding.NONE, compute_absence_days),
        _from_value(
            "E0203503",
            N_WORKPLACE_DAYS,
            Unit.DAYS,
            Rounding.NONE,
            compute_workplace_days,
            assessment=(COMMUTE_DAYS,),
        ),
        _from_value(
            "E0203504",
            N_WORKPLACE_DISTANCE,
            Unit.KM,
            Rounding.WHOLE_KM,
            compute_workplace_distance,
            assessment=(COMMUTE_KM,),
        ),
        _from_value("E0203505", N_CAR_DISTANCE, Unit.KM, Rounding.WHOLE_KM, compute_car_distance),
        _from_value(
            "E0204103",
            N_REFUND_TAX_FREE,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_BENEFITS_TAX_FREE, "Arbeitgeberleistungen laut Nr. 17"),
            Direction.INCOME,
        ),
        _from_value(
            "E0203901",
            N_REFUND_FLAT_TAXED,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_BENEFITS_FLAT_TAXED, "Arbeitgeberleistungen laut Nr. 18"),
            Direction.INCOME,
        ),
        _from_value(
            "E0204403",
            N_EQUIPMENT,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_EQUIPMENT, "Summe der Arbeitsmittel"),
            Direction.EXPENSE,
        ),
        _from_value(
            "E0204507", N_HOMEOFFICE_DAYS, Unit.DAYS, Rounding.NONE, compute_homeoffice_days
        ),
        FieldMeaning("E0204901", TypedInput(YES_NO)),
        FieldMeaning("E0205003", TypedInput()),
        _from_value(
            "E0205004",
            N_TRAVEL_FARE,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_TRAVEL_FARE, "Fahrtkosten"),
            Direction.EXPENSE,
            assessment=(BUSINESS_TRAVEL,),
        ),
        _from_value(
            "E0205518",
            N_TRAVEL_TOTAL,
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            FromValue(WORK_TRAVEL_TOTAL, "Summe der Reisekosten"),
            Direction.EXPENSE,
            assessment=(MEAL_ALLOWANCE, BUSINESS_TRAVEL),
        ),
    )


ANLAGE_N = Anlage(FORM, {2025: catalog_2025(load_structure(FORM, 2025))})
