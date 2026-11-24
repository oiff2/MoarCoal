"""Rechenkontext einer einzelnen Rechnung (docs/grundgeruest.md, 3.4)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, Protocol

from moarcoal.values.model import (
    Amount,
    ExposedValue,
    LineItem,
    Locator,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    TimeRef,
    ValueKey,
    ValueLocator,
    ValueRef,
    ValueResult,
    WorkingStep,
)

if TYPE_CHECKING:
    from moarcoal.registration import ModuleState


class NotYetSignal(Exception):
    """Die Rechnung bricht ab: noch nicht berechenbar."""

    def __init__(self, reason: str, chain: tuple[ValueRef, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.chain = chain


class NotApplicableSignal(Exception):
    """Die Rechnung bricht ab: der Wert entfällt."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ValueSource(Protocol):
    """Was eine Rechnung von `Values` braucht, um andere Werte zu verwenden."""

    def get(
        self, key: str, user: str, time: TimeRef, subject: Subject | None = None
    ) -> ValueResult: ...

    def subjects(self, key: str, user: str, time: TimeRef) -> list[Subject]: ...

    def title(self, key: str) -> str:
        """Der kurze Titel des Werts im Wertekatalog (ohne Eintrag: der Schlüssel)."""
        ...


@dataclass(frozen=True)
class Missing:
    """Ein verwendeter Wert ist noch nicht berechenbar; die Rechnung regelt das selbst."""

    result: NotYetComputable

    @property
    def reason(self) -> str:
        return self.result.reason


class Calculation:
    """Eine je Rechnung, ohne Speicherzugang: nur der eingegrenzte Stand des Moduls."""

    def __init__(
        self,
        own: "ModuleState",
        subject: Subject | None,
        time: TimeRef,
        source: ValueSource,
    ) -> None:
        self.own = own
        self.subject = subject
        self.time = time
        self._source = source
        self.items: list[LineItem] = []
        self.steps: list[WorkingStep] = []

    def item(self, label: str, amount: Amount, locator: Locator) -> LineItem:
        """Einzelposten; der Belegstand ergibt sich aus der Fundstelle."""
        line = LineItem(label, amount, locator)
        self.items.append(line)
        self.steps.append(WorkingStep("item", label, amount))
        return line

    def _fetch(
        self, key: ValueKey | str, subject: Subject | None, time: TimeRef | None
    ) -> ValueResult:
        return self._source.get(key, self.own.user, time or self.time, subject)

    def _used_item(self, result: ExposedValue, label: str | None) -> LineItem:
        locator = ValueLocator(result, self._source.title(result.key))
        return self.item(label or str(result.key), result.amount, locator)

    def _not_yet_signal(self, result: NotYetComputable) -> NotYetSignal:
        reason = f"{self._source.title(result.key)} ist noch nicht berechenbar: {result.reason}"
        return NotYetSignal(reason, (result.ref, *(link.ref for link in result.chain)))

    def use(
        self,
        key: ValueKey | str,
        subject: Subject | None = None,
        time: TimeRef | None = None,
        label: str | None = None,
    ) -> LineItem | None:
        """Einen anderen Wert verwenden, als Einzelposten mit dessen Betrag und Belegstand.

        Ist er noch nicht berechenbar, ist es diese Rechnung auch (mit Kette). Entfällt er,
        fehlt sein Einzelposten (Ergebnis `None`), und der Rechenweg nennt den Grund.
        """
        result = self._fetch(key, subject, time)
        match result:
            case ExposedValue():
                return self._used_item(result, label)
            case NotYetComputable():
                raise self._not_yet_signal(result)
            case NotApplicable():
                self.decide(f"{self._source.title(result.key)} entfällt: {result.reason}")
                return None

    def use_items(
        self, key: ValueKey | str, subject: Subject | None = None
    ) -> list[LineItem] | None:
        """Die Einzelposten eines anderen Werts als eigene übernehmen (mit deren Fundstelle),
        statt den Wert als einen Einzelposten zu verwenden, z. B. für ein Feld mit Einzelangaben.

        Ist er noch nicht berechenbar, ist es diese Rechnung auch (mit Kette). Entfällt er,
        gibt es keine (Ergebnis `None`), und der Rechenweg nennt den Grund.
        """
        result = self._fetch(key, subject, None)
        match result:
            case ExposedValue():
                return [self.item(i.label, i.amount, i.locator) for i in result.items]
            case NotYetComputable():
                raise self._not_yet_signal(result)
            case NotApplicable():
                self.decide(f"{self._source.title(result.key)} entfällt: {result.reason}")
                return None

    def require(
        self,
        key: ValueKey | str,
        subject: Subject | None = None,
        time: TimeRef | None = None,
    ) -> None:
        """Einen anderen Wert voraussetzen, ohne ihn als Einzelposten zu verwenden.

        Ist er noch nicht berechenbar oder entfällt er, ist es diese Rechnung auch."""
        result = self._fetch(key, subject, time)
        match result:
            case ExposedValue():
                return
            case NotYetComputable():
                raise self._not_yet_signal(result)
            case NotApplicable():
                raise NotApplicableSignal(
                    f"{self._source.title(result.key)} entfällt: {result.reason}"
                )

    def try_use(
        self,
        key: ValueKey | str,
        subject: Subject | None = None,
        time: TimeRef | None = None,
        label: str | None = None,
    ) -> LineItem | Missing | None:
        """Wie `use`, nur regelt die Rechnung ein Fehlen selbst (und hält es mit `decide` fest)."""
        result = self._fetch(key, subject, time)
        match result:
            case ExposedValue():
                return self._used_item(result, label)
            case NotYetComputable():
                return Missing(result)
            case NotApplicable():
                self.decide(f"{self._source.title(result.key)} entfällt: {result.reason}")
                return None

    def subjects_of(self, key: ValueKey | str, time: TimeRef | None = None) -> list[Subject]:
        """Die Bezugsobjekte, die das Modul des Schlüssels zum Zeitbezug aufzählt."""
        return self._source.subjects(key, self.own.user, time or self.time)

    def step(self, text: str, amount: Amount) -> Amount:
        """Zwischenergebnis, sichtbar im Rechenweg."""
        self.steps.append(WorkingStep("step", text, amount))
        return amount

    def decide(self, text: str) -> None:
        """Ausdrückliche Entscheidung der Rechnung, sichtbar im Rechenweg."""
        self.steps.append(WorkingStep("decision", text))

    @property
    def year(self) -> int:
        """Das Kalenderjahr des Zeitraums; bei einem Stichtag oder anderem Zeitraum: noch nicht."""
        year = self.time.calendar_year if isinstance(self.time, Period) else None
        if year is None:
            self.not_yet("Der Zeitraum ist kein Kalenderjahr")
        return year

    def not_yet(self, reason: str) -> NoReturn:
        raise NotYetSignal(reason)

    def not_applicable(self, reason: str) -> NoReturn:
        raise NotApplicableSignal(reason)
