"""Was die Rechnungen der Felder teilen: einen Wert aus einem Modul übernehmen und runden.

Der Katalog einer Anlage (`anlage_n.py`, `anlage_vor.py`, …) legt je Feld fest, was es bedeutet und
woher sein Betrag kommt (`Computed.compute`); die Schritte dazwischen stehen hier einmal.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from moarcoal.modules.tax_year.fields import FormField
from moarcoal.values.calculation import Calculation
from moarcoal.values.model import Amount, Unit, ValueKey


def rounded(calculation: Calculation, field: FormField, amount: Amount) -> Amount:
    """Rundet den Endwert nach dem Feld, mit Schritt im Rechenweg; passt er schon, ohne Schritt."""
    value, reason = field.round(amount.value)
    if reason is None:
        return amount
    return calculation.step(
        f"{field.show(amount.value)} → {field.show(value)} ({reason})",
        Amount(value, amount.unit),
    )


@dataclass(frozen=True)
class FromValue:
    """Die fertige Rechnung eines Felds, das einen Ausgewiesenen Wert über seinen Schlüssel
    übernimmt (Wert eines beliebigen Moduls, Prinzip 2); `label` nennt ihn im Rechenweg."""

    source: ValueKey
    label: str

    def __call__(self, calculation: Calculation, field: FormField) -> Amount:
        """Übernimmt den Wert des Jahrs und rundet ihn; entfällt er, entfällt das Feld."""
        item = calculation.use(self.source, label=self.label)
        if item is None:
            calculation.not_applicable(f"{self.label} entfällt")
        amount = calculation.step(f"{self.label} übernommen", item.amount)
        return rounded(calculation, field, amount)


@dataclass(frozen=True)
class ZeroIfSourceZero:
    """Die fertige Rechnung eines Felds, dessen Betrag MoarCoal sonst nicht kennt: 0 € mit
    Begründung (`reason`, im Rechenweg), wenn der Ausgewiesene Wert `source` 0 € ist; ist er größer
    als 0, ist das Feld noch nicht berechenbar (nie 0). Ist `source` noch nicht berechenbar, ist
    es das Feld auch; entfällt er, entfällt das Feld."""

    source: ValueKey
    label: str
    reason: str

    def __call__(self, calculation: Calculation, field: FormField) -> Amount:
        item = calculation.use(self.source, label=self.label)
        if item is None:
            calculation.not_applicable(f"{self.label} entfällt")
        if item.amount.value != 0:
            calculation.not_yet(f"{self.label} ist nicht 0 €, der Betrag des Felds ist offen")
        calculation.decide(f"{self.label} ist 0 €: {self.reason}")
        return rounded(calculation, field, calculation.step("Betrag des Felds", item.amount))


type CollectItems = Callable[[Calculation, FormField], None]
"""Legt die Einzelposten eines Felds mit Einzelangaben an (`Calculation.use`, `Calculation.item`):
jeder Einzelposten ist eine Einzelangabe, seine Bezeichnung ihre Bezeichnung."""


@dataclass(frozen=True)
class SumOfRounded:
    """Die fertige Rechnung der Summe eines Felds mit Einzelangaben (`Itemized.total`): jede
    Einzelangabe wird nach der Regel des Felds gerundet, die Summe ist die Summe der gerundeten
    Beträge. Ohne Einzelposten ist das Feld noch nicht berechenbar, nie 0."""

    collect: CollectItems

    def __call__(self, calculation: Calculation, field: FormField) -> Amount:
        first = len(calculation.items)
        self.collect(calculation, field)
        items = calculation.items[first:]
        if not items:
            calculation.not_yet("Es gibt noch keine Einzelposten")
        total = Decimal(0)
        for item in items:
            total += rounded(calculation, field, item.amount).value
        return calculation.step(f"Summe der {len(items)} Einzelangaben", Amount(total, Unit.EUR))
