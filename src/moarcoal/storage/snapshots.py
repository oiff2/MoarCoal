"""Baustein Schnappschuss: die zu einem Anlass eingefrorenen Ausgewiesenen Werte (Spec 3.7).

Das Format ist klein und stabil und wird nie migriert: Schlüssel, Beträge, Einzelposten und
Fundstellen stehen als einfache Zahlen und Klartext darin, ohne Verweise auf Code oder Typen.
"""

import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind

SNAPSHOT_SCHEMA = "snapshot/1"


class Occasion(StrEnum):
    """Anlass eines Schnappschusses; vorerst nur die Abgabe."""

    FILING = "filing"

    @property
    def label(self) -> str:
        return "Abgabe"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FrozenTime(_Frozen):
    """Zeitbezug: ein Zeitraum (`start`, `end`) oder ein Stichtag (`day`)."""

    start: datetime.date | None = None
    end: datetime.date | None = None
    day: datetime.date | None = None


class FrozenRef(_Frozen):
    """Nennt einen eingefrorenen Wert: Schlüssel, Bezugsobjekt (Adresse als Text) und Zeitbezug."""

    key: str = Field(min_length=1)
    subject: str = ""
    time: FrozenTime


class FrozenAmount(_Frozen):
    """Eine Zahl mit Einheit; `text` ist die Anzeige zum Zeitpunkt des Einfrierens."""

    value: Decimal
    unit: str
    text: str


class FrozenItem(_Frozen):
    """Ein Einzelposten mit Belegstand und Fundstelle als Klartext.

    `uses` nennt den Wert, auf den er sich stützt; dieser steht dann selbst im Schnappschuss.
    """

    label: str
    amount: FrozenAmount
    backing: str
    locator: str
    uses: FrozenRef | None = None


class FrozenStep(_Frozen):
    """Ein Schritt des Rechenwegs."""

    kind: str
    text: str
    amount: FrozenAmount | None = None


class FrozenValue(_Frozen):
    """Ein eingefrorener Wert samt Ergebnisart, Einzelposten, Rechenweg und Kette.

    `requested` unterscheidet die beim Einfrieren verlangten Werte von denen, auf die sie sich
    stützen.
    """

    ref: FrozenRef
    requested: bool
    outcome: Literal["amount", "not_yet", "not_applicable"]
    amount: FrozenAmount | None = None
    reason: str = ""
    backing: str = ""
    items: tuple[FrozenItem, ...] = ()
    workings: tuple[FrozenStep, ...] = ()
    chain: tuple[FrozenRef, ...] = ()


class Snapshot(Entry):
    """Eingefrorener Stand zu einem Anlass: wann, von welchem Modul und Dokument ausgelöst, für
    welchen Zeitbezug, und die Werte samt allem, worauf sie sich stützen."""

    occasion: Occasion
    taken_at: datetime.datetime
    module: str = Field(min_length=1)
    document: EntryAddress | None = None
    time: FrozenTime
    values: tuple[FrozenValue, ...]


def snapshot_path(entry: Snapshot) -> str:
    return f"users/{entry.owner}/snapshots.json"


SNAPSHOT_KIND = entry_kind(Snapshot, SNAPSHOT_SCHEMA, snapshot_path)
