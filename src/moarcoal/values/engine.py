"""`Values`: rechnet Ausgewiesene Werte auf Anfrage, mit Zwischenspeicher und Prüfungen."""

from collections.abc import Callable, Iterable, Mapping, Sequence

from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Dismissal, State
from moarcoal.values.calculation import Calculation, NotApplicableSignal, NotYetSignal
from moarcoal.values.catalog import TimeKind, ValueCatalog
from moarcoal.values.findings import (
    CYCLE,
    DUPLICATE_LOCATOR,
    Finding,
    FindingList,
    Severity,
    fingerprint,
    split_findings,
)
from moarcoal.values.model import (
    ExposedValue,
    LineItem,
    Locator,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    TimeRef,
    ValueKey,
    ValueRef,
    ValueResult,
    Workings,
)


class ContractViolation(Exception):
    """Eine Rechnung oder Anfrage bricht den Contract (Programmfehler)."""


type ForeignResult = Callable[[ValueRef], ValueResult]
"""Fest vorgegebenes Ergebnis eines fremden Werts (nur Modul-Tests, `values.testing`)."""

type Foreign = Mapping[tuple[str, Subject | None, TimeRef], ForeignResult]
"""Fremde Werte je (Schlüssel, Bezugsobjekt, Zeitbezug), die an Stelle eines Moduls stehen."""


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

    def __init__(
        self, modules: Sequence[ModuleRegistration], state: State, foreign: Foreign | None = None
    ) -> None:
        self._modules = {m.key: m for m in modules}
        self._state = state
        self.catalog = ValueCatalog.of((m.key, m.values) for m in modules)
        self._foreign = dict(foreign or {})
        self._foreign_keys = {key for key, _, _ in self._foreign}
        if both := sorted(k for k in self._foreign_keys if k in self.catalog.definitions):
            raise ContractViolation(f"angemeldet und vorgegeben: {', '.join(both)}")
        self._cache: dict[ValueRef, ValueResult] = {}
        self._stack: list[ValueRef] = []  # laufende Anfragen, zur Zykluserkennung
        self.findings: list[Finding] = []

    def _module_state(self, module_key: str, user: str) -> ModuleState:
        return ModuleState(self._state, self._modules[module_key], user)

    def get(
        self, key: str, user: str, time: TimeRef, subject: Subject | None = None
    ) -> ValueResult:
        """Ein Wert; ein unbekannter Schlüssel ist ein Programmfehler (`UnknownValueKey`)."""
        if key in self._foreign_keys:
            return self._foreign_get(key, user, time, subject)
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

    def _foreign_get(
        self, key: str, user: str, time: TimeRef, subject: Subject | None
    ) -> ValueResult:
        given = self._foreign.get((key, subject, time))
        if given is None:
            raise ContractViolation(f"{key}: keine Vorgabe für {subject} und {time}")
        return given(ValueRef(ValueKey(key), user, time, subject))

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
            found = Finding(
                DUPLICATE_LOCATOR,
                Severity.ERROR,
                value.ref,
                text,
                fingerprint=fingerprint(value.key, _describe(locator)),
            )
            self.findings.append(found)

    def _cycle(self, ref: ValueRef) -> NotYetComputable:
        """Die Anfrage läuft schon: Zyklus, mit Fehler-Befund und Kette."""
        chain = (*self._stack[self._stack.index(ref) :], ref)
        text = "Zyklus: " + " → ".join(str(r.key) for r in chain)
        members = frozenset(chain)
        if not any(f.kind == CYCLE and frozenset(f.chain) == members for f in self.findings):
            keys = sorted({str(r.key) for r in chain})
            self.findings.append(
                Finding(CYCLE, Severity.ERROR, ref, text, chain, fingerprint(*keys))
            )
        return NotYetComputable(ref.key, ref.user, ref.time, ref.subject, text)

    def finding_list(self, user: str, year: int) -> FindingList:
        """Befundliste: rechnet alle Zeitraumwerte des Jahrs, sammelt die Befunde der Datenebene
        und der Module und teilt sie nach den Ausblendungen des Nutzers. Berechnet auf Anfrage,
        nie gespeichert; Fehler zuerst."""
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
        found.sort(key=lambda f: order[f.severity])
        dismissals = [d for d in self._state.of_kind(Dismissal) if d.owner == user]
        return split_findings(found, dismissals)

    def subjects(self, key: str, user: str, time: TimeRef) -> list[Subject]:
        """Die Bezugsobjekte, die das Modul des Schlüssels zum Zeitbezug aufzählt."""
        if key in self._foreign_keys:
            found = [s for k, s, t in self._foreign if k == key and t == time and s is not None]
            return list(dict.fromkeys(found))
        definition = self.catalog.definition(key)
        if definition.subjects is None:
            raise ContractViolation(f"{definition.entry.key} hat keine Bezugsobjekte")
        owner = self.catalog.owners[definition.entry.key]
        return definition.subjects(self._module_state(owner, user), time)

    def all(self, key: str, user: str, time: TimeRef) -> list[ValueResult]:
        """Ein Ergebnis je Bezugsobjekt, das das Modul zu Schlüssel und Zeitbezug aufzählt."""
        return [self.get(key, user, time, s) for s in self.subjects(key, user, time)]
