"""Felder der Anlage N 2025, die der Durchstich abdeckt, und die Zuordnung der Werte zu ihnen.

Der Katalog enthält nur diese Felder. Ein Feld zeigt die erfassten Angaben wie ELSTER sie
verlangt, ohne Steuerrechnung (keine Entfernungspauschale). Die Werte kommen aus dem Modul Arbeit,
das das Steuerjahr nur über ihre Schlüssel kennt. Die Werte der Felder sind gesetzlich gerundet,
je nach Einheit und Richtung des Felds; der Rundungsschritt steht im Rechenweg, die Werte des Moduls
Arbeit bleiben genau (docs/recherche-runden-anlage-n.md).
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, Period, Unit, ValueKey

FORM = "N"  # Anlage N (Person A)

WORK_WORKDAYS = ValueKey("work.workdays")
WORK_DISTANCE_KM = ValueKey("work.distance_km")
WORK_EQUIPMENT = ValueKey("work.equipment")

N_WORKPLACE_DAYS = ValueKey("tax_year.n_workplace_days")
N_WORKPLACE_DISTANCE = ValueKey("tax_year.n_workplace_distance")
N_EQUIPMENT = ValueKey("tax_year.n_equipment")


class Direction(StrEnum):
    """Richtung eines Euro-Felds: Einnahme oder Ausgabe; der Wert ist die Anzeige im Rechenweg."""

    INCOME = "Einnahme"
    EXPENSE = "Ausgabe"


class Rounding(StrEnum):
    """Wie der Wert eines Felds gerundet wird, bevor er einzutragen ist."""

    WHOLE_EUROS = "ganze Euro"  # zugunsten des Steuerpflichtigen, je nach Richtung
    EURO_CENTS = "Euro mit Cent"  # exakt
    WHOLE_KM = "volle km"  # abgerundet
    NONE = "ganzzahlig"  # Tage: schon ganzzahlig


@dataclass(frozen=True)
class FormField:
    """Ein Feld einer Anlage: Bezeichnung, E-Kennung (leer, solange unbekannt), Nr. im Vordruck.

    `key` ist der Schlüssel des Ausgewiesenen Werts, den das Steuerjahr dem Feld zuordnet.
    """

    key: ValueKey
    elster_id: str | None
    form_line: str
    label: str
    unit: Unit
    rounding: Rounding
    direction: Direction | None = None  # nur bei ganzen Euro

    def __post_init__(self) -> None:
        if (self.rounding is Rounding.WHOLE_EUROS) != (self.direction is not None):
            raise ValueError(f"{self.label}: Richtung gehört genau zu Feldern mit ganzen Euro")

    @property
    def whole_numbers(self) -> bool:
        """Ob das Feld nur ganze Zahlen nimmt (Nachkommastellen heißen: ungerundet)."""
        return self.rounding is not Rounding.EURO_CENTS


def show(value: Decimal, unit: Unit) -> str:
    """Wert deutsch mit Einheit: ganze Euro ohne Cent, sonst centgenau: '87 €', '86,40 €'."""
    if unit is Unit.EUR:
        text = f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"
    else:
        text = f"{value.normalize():f}"
    text = text.replace(".", ",")
    return f"{text} €" if unit is Unit.EUR else f"{text} {unit.value}"


def round_for_field(calculation: Calculation, field: FormField, amount: Amount) -> Amount:
    """Rundet den Endwert nach dem Feld; ein Wert, der schon passt, bekommt keinen Schritt."""
    value = amount.value
    match field.rounding:
        case Rounding.WHOLE_EUROS:
            income = field.direction is Direction.INCOME
            rounded = value.to_integral_value(ROUND_FLOOR if income else ROUND_CEILING)
            how = "abgerundet" if income else "aufgerundet"
            reason = f"{how}, {field.direction}"
        case Rounding.WHOLE_KM:
            rounded = value.to_integral_value(ROUND_FLOOR)
            reason = "auf volle km abgerundet"
        case _:
            return amount
    if rounded == value:
        return amount
    return calculation.step(
        f"{show(value, amount.unit)} → {show(rounded, amount.unit)} ({reason})",
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

FORMS: dict[int, tuple[FormField, ...]] = {2025: FIELDS_2025}


def year_of(calculation: Calculation) -> int:
    time = calculation.time
    year = time.calendar_year if isinstance(time, Period) else None
    if year is None:
        calculation.not_yet("Der Zeitraum ist kein Kalenderjahr")
    return year


def _field(key: ValueKey) -> FormField:
    return next(f for f in FIELDS_2025 if f.key == key)


def _work_value(calculation: Calculation, field: FormField, source: ValueKey, label: str) -> Amount:
    """Übernimmt den Wert je erster Tätigkeitsstätte; mehrere sind noch nicht zugeordnet."""
    year = year_of(calculation)
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
    return round_for_field(calculation, field, amount)


def compute_workplace_days(calculation: Calculation) -> Amount:
    field = _field(N_WORKPLACE_DAYS)
    return _work_value(calculation, field, WORK_WORKDAYS, "Arbeitstage")


def compute_workplace_distance(calculation: Calculation) -> Amount:
    field = _field(N_WORKPLACE_DISTANCE)
    return _work_value(calculation, field, WORK_DISTANCE_KM, "Einfache Entfernung")


def compute_equipment(calculation: Calculation) -> Amount:
    year_of(calculation)
    item = calculation.use(WORK_EQUIPMENT, label="Summe der Arbeitsmittel")
    if item is None:
        calculation.not_applicable("Arbeitsmittel entfallen")
    amount = calculation.step("Summe der Arbeitsmittel übernommen", item.amount)
    return round_for_field(calculation, _field(N_EQUIPMENT), amount)


_COMPUTE = {
    N_WORKPLACE_DAYS: compute_workplace_days,
    N_WORKPLACE_DISTANCE: compute_workplace_distance,
    N_EQUIPMENT: compute_equipment,
}

VALUES: tuple[ValueDefinition, ...] = tuple(
    ValueDefinition(
        CatalogEntry(
            field.key,
            f"Anlage N 2025, {field.label}",
            field.unit,
            TimeKind.PERIOD,
        ),
        _COMPUTE[field.key],
    )
    for field in FIELDS_2025
)
