"""Felder der Anlage N je Steuerjahr, die MoarCoal abdeckt, und die Zuordnung der Werte zu ihnen.

Der Katalog enthält bisher nur die Felder des Durchstichs für 2025. Ein Feld zeigt die erfassten
Angaben wie ELSTER sie verlangt, ohne Steuerrechnung (keine Entfernungspauschale). Die Werte kommen
aus dem Modul Arbeit, das das Steuerjahr nur über ihre Schlüssel kennt. Die Werte der Felder sind
gerundet, wie das Feld es verlangt (`fields`); der Rundungsschritt steht im Rechenweg, die Werte
des Moduls Arbeit bleiben genau.
"""

from collections.abc import Callable, Mapping

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


# Quelle von E-Kennung, Nr. im Vordruck und Bezeichnung: Tage und km aus dem Feldkatalog des
# Vorgängerprojekts (Abschnitt „8 - Entfernungspauschale“), Arbeitsmittel aus der Seite
# „10 - Aufwendungen für Arbeitsmittel“ in Mein ELSTER (Summe, tools/elster_page_fields.py).
FIELDS_2025: tuple[FormField, ...] = (
    FormField(N_WORKPLACE_DAYS, "E0203503", "29", "aufgesucht an Tagen", Unit.DAYS, Rounding.NONE),
    FormField(
        N_WORKPLACE_DISTANCE,
        "E0203504",
        "30",
        "einfache Entfernung in Kilometern",
        Unit.KM,
        Rounding.WHOLE_KM,
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
    """Ein Wert je Feld, das in einem der Jahre vorkommt; die Bezeichnung aus dem jüngsten Jahr."""
    latest: dict[ValueKey, FormField] = {}
    for year in sorted(forms):
        latest.update((field.key, field) for field in forms[year])
    return tuple(
        ValueDefinition(
            CatalogEntry(field.key, f"Anlage N, {field.label}", field.unit, TimeKind.PERIOD),
            _compute(forms, field.key),
        )
        for field in latest.values()
    )
