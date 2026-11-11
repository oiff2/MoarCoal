"""Rechenkontext einer einzelnen Rechnung (docs/grundgeruest.md, 3.4)."""

from typing import TYPE_CHECKING, NoReturn

from moarcoal.values.model import Amount, LineItem, Locator, Subject, TimeRef, WorkingStep

if TYPE_CHECKING:
    from moarcoal.registration import ModuleState


class NotYetSignal(Exception):
    """Die Rechnung bricht ab: noch nicht berechenbar."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NotApplicableSignal(Exception):
    """Die Rechnung bricht ab: der Wert entfällt."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Calculation:
    """Eine je Rechnung, ohne Speicherzugang: nur der eingegrenzte Stand des Moduls."""

    def __init__(self, own: "ModuleState", subject: Subject | None, time: TimeRef) -> None:
        self.own = own
        self.subject = subject
        self.time = time
        self.items: list[LineItem] = []
        self.steps: list[WorkingStep] = []

    def item(self, label: str, amount: Amount, locator: Locator) -> LineItem:
        """Einzelposten; der Belegstand ergibt sich aus der Fundstelle."""
        line = LineItem(label, amount, locator)
        self.items.append(line)
        self.steps.append(WorkingStep("item", label, amount))
        return line

    def step(self, text: str, amount: Amount) -> Amount:
        """Zwischenergebnis, sichtbar im Rechenweg."""
        self.steps.append(WorkingStep("step", text, amount))
        return amount

    def decide(self, text: str) -> None:
        """Ausdrückliche Entscheidung der Rechnung, sichtbar im Rechenweg."""
        self.steps.append(WorkingStep("decision", text))

    def not_yet(self, reason: str) -> NoReturn:
        raise NotYetSignal(reason)

    def not_applicable(self, reason: str) -> NoReturn:
        raise NotApplicableSignal(reason)
