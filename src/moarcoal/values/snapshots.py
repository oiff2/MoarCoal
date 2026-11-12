"""Einfrieren, Vergleichen und Befunde des Schnappschusses (docs/grundgeruest.md, 3.7).

Eingefroren wird die ganze Kette: je Wert Ergebnisart, Betrag, Einzelposten mit Belegstand und
Fundstelle als Klartext, Rechenweg, und alle Werte, auf die er sich stützt. Verglichen wird ein
Schnappschuss mit dem aktuellen Stand je Stufe der Kette (`Deviation`).
"""

import datetime
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from moarcoal.storage import (
    EntryAddress,
    FrozenAmount,
    FrozenItem,
    FrozenRef,
    FrozenStep,
    FrozenTime,
    FrozenValue,
    Snapshot,
)
from moarcoal.values.calculation import ValueSource
from moarcoal.values.catalog import UnknownValueKey
from moarcoal.values.findings import Finding, Severity, fingerprint
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    KeyDate,
    NotApplicable,
    NotYetComputable,
    Period,
    Subject,
    TimeRef,
    ValueKey,
    ValueRef,
    ValueResult,
    describe_locator,
    format_amount,
)

if TYPE_CHECKING:
    from moarcoal.values.engine import Values

SNAPSHOT_NOT_YET = "snapshot_not_yet_computable"


def frozen_time(time: TimeRef) -> FrozenTime:
    match time:
        case Period(start=start, end=end):
            return FrozenTime(start=start, end=end)
        case KeyDate(day=day):
            return FrozenTime(day=day)


def thaw_time(time: FrozenTime) -> TimeRef:
    if time.day is not None:
        return KeyDate(time.day)
    assert time.start is not None and time.end is not None
    return Period(time.start, time.end)


def frozen_ref(ref: ValueRef) -> FrozenRef:
    subject = "" if ref.subject is None else str(ref.subject.address)
    return FrozenRef(key=str(ref.key), subject=subject, time=frozen_time(ref.time))


def thaw_ref(ref: FrozenRef, user: str) -> ValueRef:
    subject = Subject(EntryAddress.parse(ref.subject)) if ref.subject else None
    return ValueRef(ValueKey(ref.key), user, thaw_time(ref.time), subject)


def _amount(amount: Amount) -> FrozenAmount:
    return FrozenAmount(value=amount.value, unit=amount.unit.value, text=format_amount(amount))


def freeze_one(result: ValueResult, requested: bool = True) -> FrozenValue:
    """Ein Wert allein, ohne die Werte, auf die er sich stützt."""
    ref = frozen_ref(result.ref)
    match result:
        case ExposedValue():
            return FrozenValue(
                ref=ref,
                requested=requested,
                outcome="amount",
                amount=_amount(result.amount),
                backing=result.backing.label,
                items=tuple(
                    FrozenItem(
                        label=item.label,
                        amount=_amount(item.amount),
                        backing=item.backing.label,
                        locator=describe_locator(item.locator),
                        uses=None
                        if item.locator.used_value is None
                        else frozen_ref(item.locator.used_value.ref),
                    )
                    for item in result.items
                ),
                workings=tuple(
                    FrozenStep(
                        kind=step.kind,
                        text=step.text,
                        amount=None if step.amount is None else _amount(step.amount),
                    )
                    for step in result.workings.steps
                ),
            )
        case NotYetComputable():
            return FrozenValue(
                ref=ref,
                requested=requested,
                outcome="not_yet",
                reason=result.reason,
                chain=tuple(frozen_ref(r) for r in result.chain),
            )
        case NotApplicable():
            return FrozenValue(
                ref=ref, requested=requested, outcome="not_applicable", reason=result.reason
            )


def _dependencies(value: FrozenValue) -> Iterable[FrozenRef]:
    yield from (item.uses for item in value.items if item.uses is not None)
    yield from value.chain


def freeze(
    values: "Values", user: str, keys: Sequence[str], time: TimeRef
) -> tuple[FrozenValue, ...]:
    """Der Inhalt eines Schnappschusses: die Werte zu `keys` und `time` (bei Werten mit
    Bezugsobjekt je Bezugsobjekt) und alle Werte, auf die sie sich stützen. Die verlangten
    stehen zuerst, in der Reihenfolge von `keys`."""
    found: dict[FrozenRef, FrozenValue] = {}
    for key in keys:
        if values.catalog.definition(key).entry.has_subject:
            results = values.all(key, user, time)
        else:
            results = [values.get(key, user, time)]
        for result in results:
            found.setdefault(frozen_ref(result.ref), freeze_one(result))
    todo = [dep for value in list(found.values()) for dep in _dependencies(value)]
    while todo:
        ref = todo.pop(0)
        if ref in found:
            continue
        ready = thaw_ref(ref, user)
        value = freeze_one(values.get(ready.key, user, ready.time, ready.subject), requested=False)
        found[ref] = value
        todo.extend(_dependencies(value))
    return tuple(found.values())


class DeviationKind(StrEnum):
    """Auf welcher Stufe eines Werts der aktuelle Stand vom eingefrorenen abweicht."""

    OUTCOME = "Ergebnisart"
    AMOUNT = "Betrag"
    ITEM_ADDED = "Einzelposten hinzugekommen"
    ITEM_REMOVED = "Einzelposten weggefallen"
    ITEM_CHANGED = "Einzelposten geändert"


@dataclass(frozen=True)
class Deviation:
    """Unterschied zwischen eingefrorenem und aktuellem Stand auf einer Stufe der Kette.

    `ref` nennt den Wert, `item` bei Einzelposten dessen Bezeichnung; `frozen` und `current` sind
    die beiden Stände als Klartext (leer, wo es auf einer Seite nichts gibt).
    """

    ref: FrozenRef
    kind: DeviationKind
    frozen: str
    current: str
    item: str = ""
    frozen_amount: FrozenAmount | None = None
    current_amount: FrozenAmount | None = None

    @property
    def text(self) -> str:
        return self.text_with(lambda amount: amount.text)

    def text_with(self, show: Callable[[FrozenAmount], str]) -> str:
        """Der Text mit den Beträgen, wie `show` sie darstellt (z. B. nach dem Feld)."""

        def side(text: str, amount: FrozenAmount | None) -> str:
            return text if amount is None else text.replace(amount.text, show(amount), 1)

        frozen = side(self.frozen, self.frozen_amount)
        current = side(self.current, self.current_amount)
        what = f"{self.kind.value} {self.item}" if self.item else self.kind.value
        if not frozen:
            return f"{what}: jetzt {current}"
        if not current:
            return f"{what}: eingefroren {frozen}"
        return f"{what}: eingefroren {frozen}, jetzt {current}"


def outcome_text(value: FrozenValue) -> str:
    """Das Ergebnis eines eingefrorenen Werts als Klartext."""
    match value.outcome:
        case "amount":
            return value.amount.text if value.amount else ""
        case "not_yet":
            return f"noch nicht berechenbar ({value.reason})"
        case "not_applicable":
            return f"entfällt ({value.reason})"


def _same_amount(a: FrozenAmount, b: FrozenAmount) -> bool:
    return a.value == b.value and a.unit == b.unit


def _item_deviations(frozen: FrozenValue, current: FrozenValue) -> Iterable[Deviation]:
    unmatched = list(current.items)
    for old in frozen.items:
        match = next(
            (n for n in unmatched if (n.label, n.locator) == (old.label, old.locator)), None
        )
        if match is None:
            yield Deviation(
                frozen.ref,
                DeviationKind.ITEM_REMOVED,
                old.amount.text,
                "",
                old.label,
                frozen_amount=old.amount,
            )
            continue
        unmatched.remove(match)
        if not _same_amount(old.amount, match.amount) or old.backing != match.backing:
            yield Deviation(
                frozen.ref,
                DeviationKind.ITEM_CHANGED,
                f"{old.amount.text}, {old.backing}",
                f"{match.amount.text}, {match.backing}",
                old.label,
                frozen_amount=old.amount,
                current_amount=match.amount,
            )
    for new in unmatched:
        yield Deviation(
            frozen.ref,
            DeviationKind.ITEM_ADDED,
            "",
            new.amount.text,
            new.label,
            current_amount=new.amount,
        )


def _stage_deviations(frozen: FrozenValue, current: FrozenValue) -> Iterable[Deviation]:
    if frozen.outcome != current.outcome:
        yield Deviation(
            frozen.ref,
            DeviationKind.OUTCOME,
            outcome_text(frozen),
            outcome_text(current),
            frozen_amount=frozen.amount,
            current_amount=current.amount,
        )
        return
    if frozen.amount is None or current.amount is None:
        return  # gleiche Ergebnisart ohne Betrag: nichts zu vergleichen
    if not _same_amount(frozen.amount, current.amount):
        yield Deviation(
            frozen.ref,
            DeviationKind.AMOUNT,
            frozen.amount.text,
            current.amount.text,
            frozen_amount=frozen.amount,
            current_amount=current.amount,
        )
    yield from _item_deviations(frozen, current)


def compare(snapshot: Snapshot, values: ValueSource) -> list[Deviation]:
    """Schnappschuss gegen den aktuellen Stand, Stufe für Stufe der eingefrorenen Kette."""
    found: list[Deviation] = []
    for frozen in snapshot.values:
        ref = thaw_ref(frozen.ref, snapshot.owner)
        try:
            result = values.get(ref.key, ref.user, ref.time, ref.subject)
        except UnknownValueKey:  # Schlüssel gibt es nicht mehr (Aliasse: später)
            found.append(
                Deviation(
                    frozen.ref,
                    DeviationKind.OUTCOME,
                    outcome_text(frozen),
                    "Schlüssel nicht mehr angemeldet",
                )
            )
            continue
        found.extend(_stage_deviations(frozen, freeze_one(result, frozen.requested)))
    return found


def latest_snapshots(snapshots: Iterable[Snapshot]) -> list[Snapshot]:
    """Je Modul, Anlass und Zeitbezug der neueste Schnappschuss (Zeitpunkt, dann Kennung)."""

    def moment(snapshot: Snapshot) -> tuple[datetime.datetime, str]:
        return (snapshot.taken_at, snapshot.id)

    newest: dict[tuple[str, str, FrozenTime], Snapshot] = {}
    for snapshot in snapshots:
        identity = (snapshot.module, snapshot.occasion.value, snapshot.time)
        known = newest.get(identity)
        if known is None or moment(snapshot) > moment(known):
            newest[identity] = snapshot
    return sorted(newest.values(), key=moment)


def snapshot_findings(snapshots: Iterable[Snapshot], user: str, year: int) -> list[Finding]:
    """Befund der Datenebene: ein beim Einfrieren noch nicht berechenbarer Wert (Fehler), aus dem
    neuesten Schnappschuss je Anlass des Jahrs."""
    found: list[Finding] = []
    time = frozen_time(Period.year(year))
    mine = [s for s in snapshots if s.owner == user and s.time == time]
    for snapshot in latest_snapshots(mine):
        for value in snapshot.values:
            if value.outcome != "not_yet" or not value.requested:
                continue
            found.append(
                Finding(
                    SNAPSHOT_NOT_YET,
                    Severity.ERROR,
                    thaw_ref(value.ref, user),
                    f"{value.ref.key}: Beim Einfrieren ({snapshot.occasion.label}) war der Wert "
                    f"noch nicht berechenbar: {value.reason}",
                    fingerprint=fingerprint(snapshot.id, value.ref.key, value.reason),
                )
            )
    return found
