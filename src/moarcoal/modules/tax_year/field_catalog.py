"""Was die Kataloge der Anlagen teilen: Feld aus der Struktur bauen, Wert aus einem Modul
übernehmen und runden, Werte der berechneten Felder anmelden.

Die Anlagen (`anlage_n.py`, `anlage_vor.py`) legen nur fest, welches Feld welche Bedeutung hat und
woher sein Betrag kommt; die Schritte dazwischen stehen hier einmal.
"""

from collections.abc import Callable, Mapping

from moarcoal.modules.tax_year.fields import Direction, FormField, Forms, Rounding, TypedInput
from moarcoal.modules.tax_year.form_names import form_name
from moarcoal.modules.tax_year.structure import FormStructure
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, Unit, ValueKey

type Compute = Callable[[Calculation, FormField], Amount]
"""Wie ein Feld seinen Betrag berechnet: Rechnung und Feld (für Rundung und Bezeichnung)."""


def rounded(calculation: Calculation, field: FormField, amount: Amount) -> Amount:
    """Rundet den Endwert nach dem Feld, mit Schritt im Rechenweg; passt er schon, ohne Schritt."""
    value, reason = field.round(amount.value)
    if reason is None:
        return amount
    return calculation.step(
        f"{field.show(amount.value)} → {field.show(value)} ({reason})",
        Amount(value, amount.unit),
    )


def catalog_field(
    form: str,
    structure: FormStructure,
    key: ValueKey,
    elster_id: str,
    unit: Unit | None,
    rounding: Rounding,
    direction: Direction | None = None,
    *,
    computed: bool,
    assessment: tuple[str, ...] = (),
    printed_rounded: bool = False,
    previous: str | None = None,
    typed: TypedInput | None = None,
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
        typed=typed,
        form=form,
    )


def field_of(calculation: Calculation, form: str, forms: Forms, key: ValueKey) -> FormField:
    """Das Feld im Katalog des Steuerjahrs; ohne Katalog ist es noch nicht berechenbar."""
    year = calculation.year
    field = next((f for f in forms.get(year, ()) if f.key == key), None)
    if field is None:
        calculation.not_yet(f"{form_name(form)} {year} deckt MoarCoal noch nicht ab")
    return field


def work_total(calculation: Calculation, field: FormField, source: ValueKey, label: str) -> Amount:
    """Übernimmt den Wert des Jahrs aus dem Modul Arbeit; entfällt er, entfällt das Feld."""
    item = calculation.use(source, label=label)
    if item is None:
        calculation.not_applicable(f"{label} entfällt")
    amount = calculation.step(f"{label} übernommen", item.amount)
    return rounded(calculation, field, amount)


def values_for(
    form: str, forms: Forms, compute: Mapping[ValueKey, Compute]
) -> tuple[ValueDefinition, ...]:
    """Ein Wert je berechnetes Feld, das in einem der Jahre vorkommt; die Bezeichnung aus dem
    jüngsten Jahr. Felder, die MoarCoal noch nicht berechnet, haben keinen Wert."""
    latest: dict[ValueKey, FormField] = {}
    for year in sorted(forms):
        latest.update((field.key, field) for field in forms[year] if field.computed)

    def definition(field: FormField) -> ValueDefinition:
        def calculate(calculation: Calculation) -> Amount:
            return compute[field.key](calculation, field_of(calculation, form, forms, field.key))

        assert field.unit is not None  # berechnete Felder haben immer eine Einheit
        return ValueDefinition(
            CatalogEntry(
                field.key, f"{form_name(form)}, {field.label}", field.unit, TimeKind.PERIOD
            ),
            calculate,
        )

    return tuple(definition(field) for field in latest.values())
