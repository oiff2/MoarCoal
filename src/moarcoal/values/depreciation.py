"""Baustein AfA: lineare Absetzung für Abnutzung, monatsgenau, für jedes Modul gleich.

Was abgeschrieben wird (Arbeitsmittel, Gebäude, Einrichtung) und über wie viele Monate, entscheidet
das Modul; hier steht nur die Rechnung nach § 7 Abs. 1 EStG: gleichmäßig über die Gesamtdauer, im
ersten Jahr ab dem Monat des Beginns (der Monat zählt mit). Eine Dauer nach Prozentsatz wird zu
Monaten (2 % = 600, 2,5 % = 480, 3 % = 400). Gerundet wird die bis zum Ende eines Jahrs
aufgelaufene AfA, kaufmännisch auf Cent; so ergeben alle Jahre zusammen genau den Betrag.
Rechtslage: `docs/recherche-arbeitsmittel-afa.md`.
"""

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONTHS = 12


@dataclass(frozen=True)
class Depreciation:
    """Was ein abgeschriebener Betrag in einem Jahr zählt: `cents`; `months` von `total_months`
    sind die Monate der AfA in diesem Jahr. Beide 0: voll in diesem Jahr abgesetzt, ohne AfA."""

    cents: int
    months: int = 0
    total_months: int = 0

    @property
    def immediate(self) -> bool:
        return self.total_months == 0


def _until(cents: int, months: int, total: int) -> int:
    """Die nach `months` Monaten aufgelaufene AfA in Cent, kaufmännisch gerundet."""
    share = Decimal(cents) * min(months, total) / total
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def linear(cents: int, start: datetime.date, total_months: int, year: int) -> Depreciation | None:
    """Die lineare AfA von `cents` über `total_months` Monate ab dem Monat von `start` im Jahr
    `year`; `None`, wenn sie in `year` noch nicht oder nicht mehr läuft."""
    if total_months < 1:
        raise ValueError("Die Dauer der AfA ist mindestens ein Monat")
    first = MONTHS + 1 - start.month  # der Monat des Beginns zählt mit
    if year < start.year:
        return None
    before = 0 if year == start.year else first + (year - start.year - 1) * MONTHS
    months = min(total_months, before + (first if year == start.year else MONTHS)) - before
    if months <= 0:
        return None
    share = _until(cents, before + months, total_months) - _until(cents, before, total_months)
    return Depreciation(share, months, total_months)
