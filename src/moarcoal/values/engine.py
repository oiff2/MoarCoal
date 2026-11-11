"""`Values`: rechnet Ausgewiesene Werte auf Anfrage, mit Zwischenspeicher und Prüfungen."""

from collections.abc import Iterable, Sequence

from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Entry, State
from moarcoal.values.calculation import Calculation, NotApplicableSignal, NotYetSignal
from moarcoal.values.catalog import TimeKind, ValueCatalog
from moarcoal.values.findings import CYCLE, DUPLICATE_LOCATOR, Finding, Severity
from moarcoal.values.model import (
    ExposedValue,
    LineItem,
    Locator,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    TimeRef,
    ValueRef,
    ValueResult,
    Workings,
)


class ContractViolation(Exception):
    """Eine Rechnung oder Anfrage bricht den Contract (Programmfehler)."""


def _leaf_locators(items: Iterable[LineItem]) -> Iterable[Locator]:
    """Fundstellen der Einzelposten; Posten anderer Werte (Ketten) werden aufgeklappt."""
    for item in items:
        used = item.locator.used_value
        if used is None:
            yield item.locator
        else:
            yield from _leaf_locators(used.items)


def _describe(locator: Locator) -> str:
    address = locator.entry_address
    return f"{locator.label} {address}" if address is not None else locator.label


class Values:
    """Eine je Anfrage, auf dem festgehaltenen Stand. Rechnet jeden Wert höchstens einmal."""

    def __init__(self, modules: Sequence[ModuleRegistration], state: State) -> None:
        self._modules = {m.key: m for m in modules}
        self._state = state
        self.catalog = ValueCatalog.of((m.key, m.values) for m in modules)
        self._cache: dict[ValueRef, ValueResult] = {}
        self._stack: list[ValueRef] = []  # laufende Anfragen, zur Zykluserkennung
        self.findings: list[Finding] = []

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
        ref = ValueRef(entry.key, user, time, subject)
        cached = self._cache.get(ref)
        if cached is not None:
            return cached
        if ref in self._stack:
            return self._cycle(ref)
        calculation = Calculation(
            self._module_state(self.catalog.owners[entry.key], user), subject, time, self
        )
        result: ValueResult
        self._stack.append(ref)
        try:
            amount = definition.compute(calculation)
        except NotYetSignal as signal:
            result = NotYetComputable(entry.key, user, time, subject, signal.reason, signal.chain)
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
        finally:
            self._stack.pop()
        if isinstance(result, ExposedValue):
            self._check_duplicate_locators(result)
        self._cache[ref] = result
        return result

    def _check_duplicate_locators(self, value: ExposedValue) -> None:
        """Dieselbe Fundstelle nur einmal je Wert, auch über Ketten; sonst Fehler-Befund."""
        seen: list[Locator] = []
        duplicates: list[Locator] = []
        for locator in _leaf_locators(value.items):
            if locator in seen:
                if locator not in duplicates:
                    duplicates.append(locator)
            else:
                seen.append(locator)
        for locator in duplicates:
            text = f"Fundstelle mehrfach im Wert {value.key}: {_describe(locator)}"
            self.findings.append(Finding(DUPLICATE_LOCATOR, Severity.ERROR, value.ref, text))

    def _cycle(self, ref: ValueRef) -> NotYetComputable:
        """Die Anfrage läuft schon: Zyklus, mit Fehler-Befund und Kette."""
        chain = (*self._stack[self._stack.index(ref) :], ref)
        text = "Zyklus: " + " → ".join(str(r.key) for r in chain)
        members = frozenset(chain)
        if not any(f.kind == CYCLE and frozenset(f.chain) == members for f in self.findings):
            self.findings.append(Finding(CYCLE, Severity.ERROR, ref, text, chain))
        return NotYetComputable(ref.key, ref.user, ref.time, ref.subject, text)

    def finding_list(self, user: str, year: int) -> list[Finding]:
        """Befundliste: rechnet alle Zeitraumwerte des Jahrs, sammelt die Befunde der Datenebene
        und der Module. Berechnet auf Anfrage, nie gespeichert; Fehler zuerst."""
        period = Period.year(year)
        for entry in self.catalog.entries():
            if entry.time_kind is TimeKind.PERIOD:  # Stichtagswerte: noch nicht gebaut
                if entry.has_subject:
                    self.all(entry.key, user, period)
                else:
                    self.get(entry.key, user, period)
        found = list(self.findings)
        for module in self._modules.values():
            if module.findings is not None:
                found.extend(module.findings(self._module_state(module.key, user), self, year))
        order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.NOTE: 2}
        return sorted(found, key=lambda f: order[f.severity])

    def subjects(self, key: str, user: str, time: TimeRef) -> list[Subject]:
        """Die Bezugsobjekte, die das Modul des Schlüssels zum Zeitbezug aufzählt."""
        definition = self.catalog.definition(key)
        if definition.subjects is None:
            raise ContractViolation(f"{definition.entry.key} hat keine Bezugsobjekte")
        owner = self.catalog.owners[definition.entry.key]
        return definition.subjects(self._module_state(owner, user), time)

    def all(self, key: str, user: str, time: TimeRef) -> list[ValueResult]:
        """Ein Ergebnis je Bezugsobjekt, das das Modul zu Schlüssel und Zeitbezug aufzählt."""
        return [self.get(key, user, time, s) for s in self.subjects(key, user, time)]


def evaluate(modules: Sequence[ModuleRegistration], entries: Iterable[Entry]) -> Values:
    """Für Modul-Tests: dieselbe `Values` wie im Betrieb, der Stand aus Einträgen ohne Dateien."""
    return Values(modules, State({e.address: e for e in entries}))
