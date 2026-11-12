"""Für Modul-Tests: dieselbe `Values` wie im Betrieb, der Stand aus Einträgen ohne Dateien.

Fremde Module ersetzt `foreign` durch fest vorgegebene Ergebnisse (docs/grundgeruest.md,
Abschnitt „Modul-Tests“):

    values = evaluate(
        [tax_year_module],
        foreign={("work.equipment", None, Period.year(2025)): fixed(Amount.eur_cents(8640))},
    )
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from moarcoal.registration import ModuleRegistration
from moarcoal.storage import Entry, State
from moarcoal.values.engine import Foreign, ForeignResult, Values
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    LineItem,
    Locator,
    NotApplicable,
    NotYetComputable,
    ValueRef,
    Workings,
    WorkingStep,
)


def evaluate(
    modules: Sequence[ModuleRegistration],
    entries: Iterable[Entry] = (),
    foreign: Foreign | None = None,
) -> Values:
    """`Values` über `modules`; Schlüssel aus `foreign` stehen an Stelle anderer Module."""
    return Values(modules, State({e.address: e for e in entries}), foreign)


@dataclass(frozen=True)
class FixedLocator(Locator):
    """Fundstelle des einen Einzelpostens eines vorgegebenen Werts; je Wert eine eigene."""

    ref: ValueRef
    given_backing: Backing

    @property
    def label(self) -> str:
        return "Vorgabe im Test"

    @property
    def backing(self) -> Backing:
        return self.given_backing


def fixed(amount: Amount, backing: Backing = Backing.ASSUMED) -> ForeignResult:
    """Ein vorgegebener Betrag mit einem Einzelposten, wie ein berechneter Wert."""

    def result(ref: ValueRef) -> ExposedValue:
        item = LineItem("Vorgabe", amount, FixedLocator(ref, backing))
        workings = Workings((WorkingStep("item", "Vorgabe", amount),))
        return ExposedValue(ref.key, ref.user, ref.time, ref.subject, amount, (item,), workings)

    return result


def not_yet(reason: str) -> ForeignResult:
    """Ein vorgegebener Wert, der noch nicht berechenbar ist."""
    return lambda ref: NotYetComputable(ref.key, ref.user, ref.time, ref.subject, reason)


def not_applicable(reason: str) -> ForeignResult:
    """Ein vorgegebener Wert, der entfällt."""
    return lambda ref: NotApplicable(ref.key, ref.user, ref.time, ref.subject, reason)
