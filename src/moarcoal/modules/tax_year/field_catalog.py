"""Was die Rechnungen der Felder teilen: einen Wert aus einem Modul übernehmen und runden.

Der Katalog einer Anlage (`anlage_n.py`, `anlage_vor.py`, …) legt je Feld fest, was es bedeutet und
woher sein Betrag kommt (`Computed.compute`); die Schritte dazwischen stehen hier einmal.
"""

from dataclasses import dataclass

from moarcoal.modules.tax_year.fields import FormField
from moarcoal.values.calculation import Calculation
from moarcoal.values.model import Amount, ValueKey


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
