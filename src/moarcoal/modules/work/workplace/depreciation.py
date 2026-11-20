"""AfA der Arbeitsmittel: was eine Anschaffung in einem Steuerjahr zur Summe beiträgt.

Rechtslage und Quellen: `docs/recherche-arbeitsmittel-afa.md`. Reine Funktionen über einem
`WorkEquipment`; die Rechnung des Werts, der Schreibweg und die Seite nutzen sie gleich.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # die Eintragsart prüft mit diesen Funktionen, daher kein Import zur Laufzeit
    from moarcoal.modules.work.workplace.entries import WorkEquipment

MONTHS = 12
MAX_USEFUL_LIFE = 30  # Jahre; länger hält kein Arbeitsmittel (AfA-Tabellen: Möbel 13 Jahre)

# GWG-Grenze je Steuerjahr der Anschaffung, brutto in Cent: 800 € ohne Umsatzsteuer
# (§ 9 Abs. 1 Satz 3 Nr. 7 Satz 2 i. V. m. § 6 Abs. 2 Satz 1 EStG) mit 19 % Umsatzsteuer.
# Nur geprüfte Jahre; ein neues Jahr wird geprüft und mit Quelle nachgetragen, nie fortgeschrieben.
GWG_LIMITS: dict[int, int] = dict.fromkeys(range(2018, 2027), 95_200)
GWG_SOURCE = "§ 6 Abs. 2 EStG, geprüft am 20.11.2026 (docs/recherche-arbeitsmittel-afa.md)"


@dataclass(frozen=True)
class Depreciation:
    """Was eine Anschaffung in einem Steuerjahr zählt: `cents`; `months` von `total_months` sind
    die Monate der AfA in diesem Jahr, beide 0 bei einem GWG (voll im Jahr der Anschaffung)."""

    cents: int
    months: int = 0
    total_months: int = 0

    @property
    def immediate(self) -> bool:
        return self.total_months == 0


def gwg_limit(year: int) -> int | None:
    """Die GWG-Grenze (Cent, brutto) für Anschaffungen in `year`, `None` = noch nicht geprüft."""
    return GWG_LIMITS.get(year)


def above_limit(purchase: "WorkEquipment") -> bool | None:
    """Ob die Anschaffung über der GWG-Grenze ihres Jahrs liegt; `None`, wenn die Grenze für das
    Jahr noch nicht geprüft ist."""
    limit = gwg_limit(purchase.year)
    return None if limit is None else purchase.input.amount_cents > limit


def needs_useful_life(purchase: "WorkEquipment") -> bool:
    """Über der GWG-Grenze, aber ohne Nutzungsdauer (etwa ein Eintrag von vor der AfA)."""
    return above_limit(purchase) is True and purchase.useful_life_years is None


def _until(cents: int, months: int, total: int) -> int:
    """Die bis dahin aufgelaufene AfA in Cent, kaufmännisch gerundet."""
    share = Decimal(cents) * min(months, total) / total
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def depreciation(purchase: "WorkEquipment", year: int) -> Depreciation | str | None:
    """Was `purchase` in `year` zählt; `None`, wenn nichts (noch nicht angeschafft, voll in einem
    früheren Jahr oder AfA vorbei); Text: warum es noch nicht feststeht."""
    bought = purchase.year
    if year < bought or year > bought + MAX_USEFUL_LIFE:
        return None
    above = above_limit(purchase)
    if above is None:
        return f"GWG-Grenze für {bought} noch nicht geprüft"
    cents = purchase.input.amount_cents
    life = purchase.useful_life_years
    if not above or life == 1:  # GWG; ein Jahr: voll im Jahr der Anschaffung (BMF, Rz. 1.4)
        return Depreciation(cents) if year == bought else None
    name = purchase.input.description
    if life is None:
        return f"Nutzungsdauer von „{name}“ ({bought}) fehlt"
    if purchase.input.date.year != bought:
        return f"Datum der Anschaffung von „{name}“ liegt nicht in {bought}"
    total = life * MONTHS
    first = MONTHS + 1 - purchase.input.date.month  # der Monat der Anschaffung zählt mit
    before = 0 if year == bought else first + (year - bought - 1) * MONTHS
    months = min(total, before + (first if year == bought else MONTHS)) - before
    if months <= 0:
        return None
    share = _until(cents, before + months, total) - _until(cents, before, total)
    return Depreciation(share, months, total)
