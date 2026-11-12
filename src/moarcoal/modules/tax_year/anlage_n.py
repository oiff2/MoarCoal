"""Felder der Anlage N je Steuerjahr und die Zuordnung der Werte zu ihnen.

Der Katalog enthält alle für 2025 bekannten Felder; berechnet werden bisher nur die des Durchstichs
(`FormField.computed`). Ein Feld zeigt die erfassten Angaben wie ELSTER sie verlangt, ohne
Steuerrechnung (keine Entfernungspauschale). Die Werte kommen aus dem Modul Arbeit, das das
Steuerjahr nur über ihre Schlüssel kennt. Die Werte der Felder sind
gerundet, wie das Feld es verlangt (`fields`); der Rundungsschritt steht im Rechenweg, die Werte
des Moduls Arbeit bleiben genau.
"""

from collections.abc import Callable, Mapping

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
# (`computed`). Die Positionen des Bescheids (`assessment`) und welche er gerundet druckt, hat der
# Mensch an einem echten Bescheid zugeordnet (#54).
def _known(
    name: str,
    elster_id: str,
    form_line: str,
    label: str,
    unit: Unit | None,
    rounding: Rounding,
    direction: Direction | None = None,
    *,
    assessment: tuple[str, ...] = (),
    printed_rounded: bool = False,
) -> FormField:
    """Ein Feld des Katalogs, das MoarCoal bisher nicht berechnet."""
    return FormField(
        ValueKey(f"tax_year.n_{name}"),
        elster_id,
        form_line,
        label,
        unit,
        rounding,
        direction,
        computed=False,
        assessment=assessment,
        printed_rounded=printed_rounded,
    )


FIELDS_2025: tuple[FormField, ...] = (
    _known("tax_class", "E0200002", "4", "Steuerklasse", None, Rounding.NONE),
    _known(
        "gross_wages",
        "E0200201",
        "5",
        "Bruttoarbeitslohn einschließlich Sachbezüge (Summe)",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.INCOME,
        assessment=(GROSS_WAGES,),
    ),
    _known(
        "gross_wages_single",
        "E0200204",
        "5",
        "Bruttoarbeitslohn einschließlich Sachbezüge (je Bescheinigung)",
        Unit.EUR,
        Rounding.EURO_CENTS,
    ),
    _known(
        "income_tax",
        "E0200301",
        "6",
        "Lohnsteuer (Summe)",
        Unit.EUR,
        Rounding.EURO_CENTS,
        assessment=(INCOME_TAX_WITHHELD,),
        printed_rounded=True,
    ),
    _known(
        "income_tax_single",
        "E0200304",
        "6",
        "Lohnsteuer (je Bescheinigung)",
        Unit.EUR,
        Rounding.EURO_CENTS,
    ),
    _known(
        "soli",
        "E0200401",
        "7",
        "Solidaritätszuschlag (Summe)",
        Unit.EUR,
        Rounding.EURO_CENTS,
        assessment=(SOLI_WITHHELD,),
    ),
    _known(
        "soli_single",
        "E0200404",
        "7",
        "Solidaritätszuschlag (je Bescheinigung)",
        Unit.EUR,
        Rounding.EURO_CENTS,
    ),
    _known("workplace_target", "E0203003", "27", "Ziel des Weges", None, Rounding.NONE),
    _known("workplace_address", "E0203501", "27", "PLZ, Ort und Straße", None, Rounding.NONE),
    _known("workplace_period", "E0203101", "27", "vom - bis", None, Rounding.NONE),
    _known("workdays_per_week", "E0203508", "28", "Arbeitstage je Woche", Unit.DAYS, Rounding.NONE),
    _known(
        "absence_days",
        "E0203509",
        "28",
        "Urlaubs-, Krankheits-, Heimarbeits- und Dienstreisetage",
        Unit.DAYS,
        Rounding.NONE,
    ),
    FormField(
        N_WORKPLACE_DAYS,
        "E0203503",
        "29",
        "aufgesucht an Tagen",
        Unit.DAYS,
        Rounding.NONE,
        assessment=(COMMUTE_DAYS,),
    ),
    FormField(
        N_WORKPLACE_DISTANCE,
        "E0203504",
        "30",
        "einfache Entfernung in Kilometern",
        Unit.KM,
        Rounding.WHOLE_KM,
        assessment=(COMMUTE_KM,),
    ),
    _known(
        "car_distance",
        "E0203505",
        "31",
        "davon mit eigenem oder zur Nutzung überlassenem PKW zurückgelegt",
        Unit.KM,
        Rounding.WHOLE_KM,
    ),
    _known(
        "refund_tax_free",
        "E0204103",
        "51",
        "Arbeitgeberleistungen laut Nr. 17 der Lohnsteuerbescheinigung (steuerfrei ersetzt)",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.INCOME,
    ),
    _known(
        "refund_flat_taxed",
        "E0203901",
        "51",
        "Arbeitgeberleistungen laut Nr. 18 der Lohnsteuerbescheinigung (pauschal besteuert)",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.INCOME,
    ),
    FormField(
        N_EQUIPMENT,
        "E0204403",
        "56",
        "Arbeitsmittel",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.EXPENSE,
    ),
    _known(
        "homeoffice_days",
        "E0204507",
        "58",
        "Kalendertage, an denen die berufliche Tätigkeit überwiegend in der häuslichen Wohnung "
        "ausgeübt wurde",
        Unit.DAYS,
        Rounding.NONE,
    ),
    _known(
        "company_car",
        "E0204901",
        "65",
        "Fahrten mit Firmenwagen oder unentgeltlicher Sammelbeförderung",
        None,
        Rounding.NONE,
    ),
    _known("travel_fare_kind", "E0205003", "66", "Fahrtkosten (Art)", None, Rounding.NONE),
    _known(
        "travel_fare",
        "E0205004",
        "66",
        "Fahrtkosten (Betrag)",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.EXPENSE,
        assessment=(BUSINESS_TRAVEL,),
    ),
    _known(
        "travel_total",
        "E0205518",
        "69",
        "Gesamtsumme der Aufwendungen für Reisekosten",
        Unit.EUR,
        Rounding.WHOLE_EUROS,
        Direction.EXPENSE,
        assessment=(MEAL_ALLOWANCE, BUSINESS_TRAVEL),
    ),
)

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
