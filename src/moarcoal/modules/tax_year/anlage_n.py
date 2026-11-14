"""Felder der Anlage N je Steuerjahr und die Zuordnung der Werte zu ihnen.

Der Katalog enthält alle für 2025 bekannten Felder; berechnet werden bisher nur die des Durchstichs
(`FormField.computed`). Ein Feld zeigt die erfassten Angaben wie ELSTER sie verlangt, ohne
Steuerrechnung (keine Entfernungspauschale). Die Werte kommen aus dem Modul Arbeit, das das
Steuerjahr nur über ihre Schlüssel kennt. Die Werte der Felder sind
gerundet, wie das Feld es verlangt (`fields`); der Rundungsschritt steht im Rechenweg, die Werte
des Moduls Arbeit bleiben genau.
"""

from collections.abc import Callable, Mapping
from functools import partial

from moarcoal.modules.tax_year.assessment import (
    BUSINESS_TRAVEL,
    COMMUTE_DAYS,
    COMMUTE_KM,
    GROSS_WAGES,
    INCOME_TAX_WITHHELD,
    MEAL_ALLOWANCE,
    SOLI_WITHHELD,
)
from moarcoal.modules.tax_year.fields import Direction, FormField, Rounding
from moarcoal.modules.tax_year.structure import FormStructure, load_structure
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, Unit, ValueKey

FORM = "N"  # Anlage N (Person A)

WORK_WORKDAYS = ValueKey("work.workdays")
WORK_DISTANCE_KM = ValueKey("work.distance_km")
WORK_EQUIPMENT = ValueKey("work.equipment")

N_WORKPLACE_DAYS = ValueKey("tax_year.n_workplace_days")
N_WORKPLACE_DISTANCE = ValueKey("tax_year.n_workplace_distance")
N_EQUIPMENT = ValueKey("tax_year.n_equipment")


def _rounded(calculation: Calculation, field: FormField, amount: Amount) -> Amount:
    """Rundet den Endwert nach dem Feld, mit Schritt im Rechenweg; passt er schon, ohne Schritt."""
    rounded, reason = field.round(amount.value)
    if reason is None:
        return amount
    return calculation.step(
        f"{field.show(amount.value)} → {field.show(rounded)} ({reason})",
        Amount(rounded, amount.unit),
    )


# Quelle von E-Kennung, Nr. im Vordruck und Bezeichnung: das Übertragungsprotokoll der Abgabe 2025
# (E-Kennung, Zeile, Bezeichnung; keine Beträge), für Arbeitsmittel die Seite „10 - Aufwendungen
# für Arbeitsmittel“ in Mein ELSTER (Summe, tools/elster_page_fields.py). Der Katalog nimmt alle
# bekannten Felder mit; berechnet werden bisher nur die drei mit Quelle im Modul Arbeit
# (`computed`). Die Positionen des EStB (`assessment`) und welche er gerundet druckt, hat der
# Mensch an einem echten EStB zugeordnet (#54).
def _catalog_field(
    structure: FormStructure,
    key: ValueKey,
    elster_id: str,
    unit: Unit | None,
    rounding: Rounding,
    direction: Direction | None,
    *,
    computed: bool,
    assessment: tuple[str, ...],
    printed_rounded: bool,
    previous: str | None,
) -> FormField:
    """Ein Feld des Katalogs: Bedeutung aus den Argumenten, Nr. und Bezeichnung aus der Struktur."""
    described = structure.get(elster_id)
    return FormField(
        key,
        elster_id,
        described.line,
        described.label,
        unit,
        rounding,
        direction,
        computed=computed,
        assessment=assessment,
        printed_rounded=printed_rounded,
        previous=previous,
    )


def _known(
    structure: FormStructure,
    name: str,
    elster_id: str,
    unit: Unit | None,
    rounding: Rounding,
    direction: Direction | None = None,
    *,
    assessment: tuple[str, ...] = (),
    printed_rounded: bool = False,
    previous: str | None = None,
) -> FormField:
    """Ein Feld des Katalogs, das MoarCoal bisher nicht berechnet."""
    return _catalog_field(
        structure,
        ValueKey(f"tax_year.n_{name}"),
        elster_id,
        unit,
        rounding,
        direction,
        computed=False,
        assessment=assessment,
        printed_rounded=printed_rounded,
        previous=previous,
    )


def _computed(
    structure: FormStructure,
    key: ValueKey,
    elster_id: str,
    unit: Unit,
    rounding: Rounding,
    direction: Direction | None = None,
    *,
    assessment: tuple[str, ...] = (),
    previous: str | None = None,
) -> FormField:
    """Ein Feld des Katalogs, das MoarCoal berechnet."""
    return _catalog_field(
        structure,
        key,
        elster_id,
        unit,
        rounding,
        direction,
        computed=True,
        assessment=assessment,
        printed_rounded=False,
        previous=previous,
    )


def fields_n(structure: FormStructure) -> tuple[FormField, ...]:
    """Die Felder der Anlage N: Bedeutung aus dem Katalog, Bezeichnung und Nr. aus der Struktur."""
    known = partial(_known, structure)
    computed = partial(_computed, structure)
    return (
        known("tax_class", "E0200002", None, Rounding.NONE),
        known(
            "gross_wages",
            "E0200201",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.INCOME,
            assessment=(GROSS_WAGES,),
        ),
        known(
            "gross_wages_single",
            "E0200204",
            Unit.EUR,
            Rounding.EURO_CENTS,
        ),
        known(
            "income_tax",
            "E0200301",
            Unit.EUR,
            Rounding.EURO_CENTS,
            assessment=(INCOME_TAX_WITHHELD,),
            printed_rounded=True,
        ),
        known(
            "income_tax_single",
            "E0200304",
            Unit.EUR,
            Rounding.EURO_CENTS,
        ),
        known(
            "soli",
            "E0200401",
            Unit.EUR,
            Rounding.EURO_CENTS,
            assessment=(SOLI_WITHHELD,),
        ),
        known(
            "soli_single",
            "E0200404",
            Unit.EUR,
            Rounding.EURO_CENTS,
        ),
        known("workplace_target", "E0203003", None, Rounding.NONE),
        known("workplace_address", "E0203501", None, Rounding.NONE),
        known("workplace_period", "E0203101", None, Rounding.NONE),
        known("workdays_per_week", "E0203508", Unit.DAYS, Rounding.NONE),
        known(
            "absence_days",
            "E0203509",
            Unit.DAYS,
            Rounding.NONE,
        ),
        computed(
            N_WORKPLACE_DAYS,
            "E0203503",
            Unit.DAYS,
            Rounding.NONE,
            assessment=(COMMUTE_DAYS,),
        ),
        computed(
            N_WORKPLACE_DISTANCE,
            "E0203504",
            Unit.KM,
            Rounding.WHOLE_KM,
            assessment=(COMMUTE_KM,),
        ),
        known(
            "car_distance",
            "E0203505",
            Unit.KM,
            Rounding.WHOLE_KM,
        ),
        known(
            "refund_tax_free",
            "E0204103",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.INCOME,
        ),
        known(
            "refund_flat_taxed",
            "E0203901",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.INCOME,
        ),
        computed(
            N_EQUIPMENT,
            "E0204403",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.EXPENSE,
        ),
        known(
            "homeoffice_days",
            "E0204507",
            Unit.DAYS,
            Rounding.NONE,
        ),
        known(
            "company_car",
            "E0204901",
            None,
            Rounding.NONE,
        ),
        known("travel_fare_kind", "E0205003", None, Rounding.NONE),
        known(
            "travel_fare",
            "E0205004",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.EXPENSE,
            assessment=(BUSINESS_TRAVEL,),
        ),
        known(
            "travel_total",
            "E0205518",
            Unit.EUR,
            Rounding.WHOLE_EUROS,
            Direction.EXPENSE,
            assessment=(MEAL_ALLOWANCE, BUSINESS_TRAVEL),
        ),
    )


STRUCTURES: Mapping[int, FormStructure] = {2025: load_structure(FORM, 2025)}
FIELDS_2025 = fields_n(STRUCTURES[2025])

type Forms = Mapping[int, tuple[FormField, ...]]
"""Felder der Anlage N je Steuerjahr."""

FORMS: Forms = {2025: FIELDS_2025}


def _field(calculation: Calculation, forms: Forms, key: ValueKey) -> FormField:
    """Das Feld im Katalog des Steuerjahrs; ohne Katalog ist es noch nicht berechenbar."""
    year = calculation.year
    field = next((f for f in forms.get(year, ()) if f.key == key), None)
    if field is None:
        calculation.not_yet(f"Anlage N {year} deckt MoarCoal noch nicht ab")
    return field


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
    return _rounded(calculation, field, amount)


def compute_workplace_days(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_WORKDAYS, "Arbeitstage")


def compute_workplace_distance(calculation: Calculation, field: FormField) -> Amount:
    return _work_value(calculation, field, WORK_DISTANCE_KM, "Einfache Entfernung")


def compute_equipment(calculation: Calculation, field: FormField) -> Amount:
    item = calculation.use(WORK_EQUIPMENT, label="Summe der Arbeitsmittel")
    if item is None:
        calculation.not_applicable("Arbeitsmittel entfallen")
    amount = calculation.step("Summe der Arbeitsmittel übernommen", item.amount)
    return _rounded(calculation, field, amount)


_COMPUTE: dict[ValueKey, Callable[[Calculation, FormField], Amount]] = {
    N_WORKPLACE_DAYS: compute_workplace_days,
    N_WORKPLACE_DISTANCE: compute_workplace_distance,
    N_EQUIPMENT: compute_equipment,
}


def _compute(forms: Forms, key: ValueKey) -> Callable[[Calculation], Amount]:
    def compute(calculation: Calculation) -> Amount:
        return _COMPUTE[key](calculation, _field(calculation, forms, key))

    return compute


def values_for(forms: Forms) -> tuple[ValueDefinition, ...]:
    """Ein Wert je berechnetes Feld, das in einem der Jahre vorkommt; die Bezeichnung aus dem
    jüngsten Jahr. Felder, die MoarCoal noch nicht berechnet, haben keinen Wert."""
    latest: dict[ValueKey, FormField] = {}
    for year in sorted(forms):
        latest.update((field.key, field) for field in forms[year] if field.computed)
    return tuple(
        ValueDefinition(
            CatalogEntry(field.key, f"Anlage N, {field.label}", field.unit, TimeKind.PERIOD),
            _compute(forms, field.key),
        )
        for field in latest.values()
        if field.unit is not None  # berechnete Felder haben immer eine Einheit
    )
