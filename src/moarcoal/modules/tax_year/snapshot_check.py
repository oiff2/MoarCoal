"""Schnappschuss der Abgabe: beim Aufnehmen des Protokolls einfrieren, später Abweichungen der
aktuellen Werte davon melden (Befunde)."""

import datetime
from collections.abc import Sequence

from moarcoal.modules.tax_year.anlagen import Anlage, field_catalog
from moarcoal.modules.tax_year.entries import MODULE_KEY, ProtocolReading
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.links import anlage_url
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Document, Entry, FrozenValue, Occasion, Put, Snapshot
from moarcoal.values.calculation import ValueSource
from moarcoal.values.engine import Values
from moarcoal.values.findings import Finding, FindingKind, Severity, fingerprint
from moarcoal.values.model import Period, ValueRef
from moarcoal.values.snapshots import (
    compare,
    freeze,
    frozen_time,
    latest_snapshots,
    outcome_text,
)

SNAPSHOT_DEVIATION = "tax_year.snapshot_deviation"

FINDING_KINDS = (FindingKind(SNAPSHOT_DEVIATION, "Abweichung zum Schnappschuss"),)


def latest_snapshot(state: ModuleState, year: int) -> Snapshot | None:
    """Der neueste Schnappschuss der Abgabe des Jahrs, den dieses Modul ausgelöst hat."""
    time = frozen_time(Period.year(year))
    found = [s for s in state.snapshots() if s.occasion is Occasion.FILING and s.time == time]
    return latest_snapshots(found)[-1] if found else None


def describe_frozen(field: FormField, frozen: FrozenValue) -> str:
    """Der eingefrorene Wert eines Felds als Klartext, ganze Euro ohne Cent."""
    if frozen.outcome == "amount" and frozen.amount is not None:
        return field.show(frozen.amount.value)
    return outcome_text(frozen)


def snapshot_findings(
    state: ModuleState, values: ValueSource, year: int, anlagen: Sequence[Anlage] = ANLAGEN
) -> list[Finding]:
    """Warnung je Feld, dessen aktueller Wert vom eingefrorenen der Abgabe abweicht; verglichen
    wird mit dem neuesten Schnappschuss des Jahrs."""
    snapshot = latest_snapshot(state, year)
    if snapshot is None:
        return []
    deviations = compare(snapshot, values)
    period = Period.year(year)
    found: list[Finding] = []
    for anlage in anlagen:
        for field in anlage.forms.get(year, ()):
            mine = [
                d
                for d in deviations
                if d.ref.key == field.key and d.ref.time == frozen_time(period)
            ]
            if not mine:
                continue
            taken = snapshot.taken_at.strftime("%d.%m.%Y")
            texts = [d.text_with(lambda amount, f=field: f.show(amount.value)) for d in mine]
            found.append(
                Finding(
                    SNAPSHOT_DEVIATION,
                    Severity.WARNING,
                    ValueRef(field.key, state.user, period, None),
                    f"{field.name}: Abweichung zum Schnappschuss bei Abgabe am {taken}. "
                    + "; ".join(texts),
                    href=anlage_url(anlage.slug, year),
                    fingerprint=fingerprint(snapshot.id, field.key, *texts),
                )
            )
    return found


def snapshot_on_filing(
    document: Document,
    entries: Sequence[Entry],
    values: Values,
    anlagen: Sequence[Anlage] = ANLAGEN,
) -> Sequence[Change]:
    """Ergänzung beim Aufnehmen eines Protokolls (Spec 3.6 Punkt 8): friert die Werte der Felder
    des Jahrs aller Anlagen als Schnappschuss der Abgabe ein. Jahre ohne Felder (vor 2025): keiner;
    gibt es für das Jahr schon einen Schnappschuss der Abgabe, auch keiner (der alte gibt den
    Stand der Abgabe wieder, etwa nach Löschen und erneutem Aufnehmen des Protokolls)."""
    reading = next((e for e in entries if isinstance(e, ProtocolReading)), None)
    fields = () if reading is None else field_catalog(anlagen, reading.year)
    if reading is None or not fields:
        return []
    if latest_snapshot(values.module_state(MODULE_KEY, document.owner), reading.year):
        return []
    period = Period.year(reading.year)
    snapshot = Snapshot(
        owner=document.owner,
        occasion=Occasion.FILING,
        taken_at=document.taken_in_at or datetime.datetime.now(datetime.UTC),
        module=MODULE_KEY,
        document=document.address,
        time=frozen_time(period),
        values=freeze(values, document.owner, [f.key for f in fields if f.computed], period),
    )
    return [Put(snapshot)]
