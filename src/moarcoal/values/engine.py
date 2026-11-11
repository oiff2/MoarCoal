"""`Values`: rechnet Ausgewiesene Werte auf Anfrage, mit Zwischenspeicher und Prüfungen."""

from collections.abc import Iterable, Sequence

from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Entry, State
from moarcoal.values.calculation import Calculation, NotApplicableSignal, NotYetSignal
from moarcoal.values.catalog import TimeKind, ValueCatalog
from moarcoal.values.model import (
    ExposedValue,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    TimeRef,
    ValueKey,
    ValueResult,
    Workings,
)


class ContractViolation(Exception):
    """Eine Rechnung oder Anfrage bricht den Contract (Programmfehler)."""


class Values:
    """Eine je Anfrage, auf dem festgehaltenen Stand. Rechnet jeden Wert höchstens einmal."""

    def __init__(self, modules: Sequence[ModuleRegistration], state: State) -> None:
        self._modules = {m.key: m for m in modules}
        self._state = state
        self.catalog = ValueCatalog.of((m.key, m.values) for m in modules)
        self._cache: dict[tuple[ValueKey, str, TimeRef, Subject | None], ValueResult] = {}

    def _module_state(self, module_key: str, user: str) -> ModuleState:
        return ModuleState(self._state, self._modules[module_key], user)

    def get(
        self, key: str, user: str, time: TimeRef, subject: Subject | None = None
    ) -> ValueResult:
        """Ein Wert; ein unbekannter Schlüssel ist ein Programmfehler (`UnknownValueKey`)."""
        definition = self.catalog.definition(key)
        entry = definition.entry
        if (entry.time_kind is TimeKind.PERIOD) != isinstance(time, Period):
            raise ContractViolation(f"{entry.key}: Zeitbezug passt nicht zu {entry.time_kind}")
        if entry.has_subject != (subject is not None):
            raise ContractViolation(f"{entry.key}: Bezugsobjekt nötig: {entry.has_subject}")
        cache_key = (entry.key, user, time, subject)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        calculation = Calculation(
            self._module_state(self.catalog.owners[entry.key], user), subject, time
        )
        result: ValueResult
        try:
            amount = definition.compute(calculation)
        except NotYetSignal as signal:
            result = NotYetComputable(entry.key, user, time, subject, signal.reason)
        except NotApplicableSignal as signal:
            result = NotApplicable(entry.key, user, time, subject, signal.reason)
        else:
            if amount.unit != entry.unit:
                raise ContractViolation(
                    f"{entry.key}: Einheit {amount.unit} statt {entry.unit} laut Wertekatalog"
                )
            result = ExposedValue(
                entry.key,
                user,
                time,
                subject,
                amount,
                tuple(calculation.items),
                Workings(tuple(calculation.steps)),
            )
        self._cache[cache_key] = result
        return result

    def all(self, key: str, user: str, time: TimeRef) -> list[ValueResult]:
        """Ein Ergebnis je Bezugsobjekt, das das Modul zu Schlüssel und Zeitbezug aufzählt."""
        definition = self.catalog.definition(key)
        if definition.subjects is None:
            raise ContractViolation(f"{definition.entry.key} hat keine Bezugsobjekte")
        module_state = self._module_state(self.catalog.owners[definition.entry.key], user)
        return [self.get(key, user, time, s) for s in definition.subjects(module_state, time)]


def evaluate(modules: Sequence[ModuleRegistration], entries: Iterable[Entry]) -> Values:
    """Für Modul-Tests: dieselbe `Values` wie im Betrieb, der Stand aus Einträgen ohne Dateien."""
    return Values(modules, State({e.address: e for e in entries}))
