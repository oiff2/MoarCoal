"""AfA der Arbeitsmittel: was eine Anschaffung in einem Steuerjahr zur Summe beiträgt.

Hier stehen nur die Regeln der Arbeitsmittel (GWG-Grenze je Jahr, Nutzungsdauer in Jahren, ein
Jahr voll nach BMF); gerechnet wird mit dem Baustein `values.depreciation`. Rechtslage und Quellen:
`docs/recherche-arbeitsmittel-afa.md`. Die Rechnung des Werts, der Schreibweg und die Seite nutzen
diese Funktionen gleich.
"""

from typing import TYPE_CHECKING

from moarcoal.values.depreciation import MONTHS, Depreciation, linear
from moarcoal.values.model import format_eur

if TYPE_CHECKING:  # die Eintragsart prüft mit diesen Funktionen, daher kein Import zur Laufzeit
    from moarcoal.modules.work.workplace.entries import WorkEquipment

MAX_USEFUL_LIFE = 30  # Jahre; länger hält kein Arbeitsmittel (AfA-Tabellen: Möbel 13 Jahre)

# GWG-Grenze je Steuerjahr der Anschaffung, brutto in Cent: 800 € ohne Umsatzsteuer
# (§ 9 Abs. 1 Satz 3 Nr. 7 Satz 2 i. V. m. § 6 Abs. 2 Satz 1 EStG) mit 19 % Umsatzsteuer.
# Nur geprüfte Jahre; ein neues Jahr wird geprüft und mit Quelle nachgetragen, nie fortgeschrieben.
GWG_LIMITS: dict[int, int] = dict.fromkeys(range(2018, 2027), 95_200)
LATEST_CHECKED = max(GWG_LIMITS)
# Ein Jahr Nutzungsdauer voll im Jahr der Anschaffung (BMF vom 22.02.2022, Rz. 1.4) gilt für
# Arbeitsmittel ab diesem Jahr (Rz. 7); davor wird auch ein Jahr anteilig verteilt.
ONE_YEAR_IN_FULL_FROM = 2021
GWG_SOURCE = "§ 6 Abs. 2 EStG, geprüft am 20.11.2026 (docs/recherche-arbeitsmittel-afa.md)"


def gwg_limit(year: int) -> int | None:
    """Die GWG-Grenze (Cent, brutto) für Anschaffungen in `year`, `None` = noch nicht geprüft."""
    return GWG_LIMITS.get(year)


def above_limit(purchase: "WorkEquipment") -> bool | None:
    """Ob die Anschaffung über der GWG-Grenze ihres Jahrs liegt; `None`, wenn das nach Betrag
    nicht sicher ist.

    Ist die Grenze des Jahrs noch nicht geprüft, ist nur ein Jahr nach der Tabelle bis zur zuletzt
    geprüften Grenze sicher GWG (die Grenze sinkt nicht); darüber wird das Jahr geprüft und
    nachgetragen. Jahre vor der Tabelle bleiben offen (für sie kommt nichts Neues hinzu)."""
    cents, year = purchase.input.amount_cents, purchase.year
    limit = gwg_limit(year)
    if limit is not None:
        return cents > limit
    if year > LATEST_CHECKED and cents <= GWG_LIMITS[LATEST_CHECKED]:
        return False
    return None


def limit_text(year: int) -> str:
    """Die Grenze, an der eine Anschaffung aus `year` gemessen wird, für den Rechenweg."""
    limit = gwg_limit(year)
    if limit is not None:
        return f"GWG-Grenze {year}: {format_eur(limit)}"
    latest = f"{LATEST_CHECKED} ({format_eur(GWG_LIMITS[LATEST_CHECKED])})"
    return f"GWG-Grenze {year} noch nicht geprüft, bis zu der von {latest} sicher"


def needs_useful_life(purchase: "WorkEquipment") -> bool:
    """Über der GWG-Grenze, aber ohne Nutzungsdauer (etwa ein Eintrag von vor der AfA)."""
    return above_limit(purchase) is True and purchase.useful_life_years is None


def counted_useful_life(purchase: "WorkEquipment") -> int | None:
    """Die Nutzungsdauer, die zählt: nur über der GWG-Grenze; bis zur Grenze bleibt eine
    eingetragene ungenutzt (voller Betrag im Jahr der Anschaffung)."""
    return purchase.useful_life_years if above_limit(purchase) else None


def in_full(purchase: "WorkEquipment") -> bool:
    """Ob der volle Betrag im Jahr der Anschaffung zählt: GWG, oder ab 2021 ein Jahr
    Nutzungsdauer (BMF, Rz. 1.4 und 7)."""
    life = counted_useful_life(purchase)
    return life is None or (life == 1 and purchase.year >= ONE_YEAR_IN_FULL_FROM)


def missing(purchase: "WorkEquipment") -> str | None:
    """Was einer Anschaffung über der GWG-Grenze für die AfA fehlt, als Text; sonst `None`.

    Schreibweg und Rechnung des Werts prüfen damit dasselbe."""
    name, bought = purchase.input.description, purchase.year
    if needs_useful_life(purchase):
        limit = format_eur(GWG_LIMITS[bought])
        return (
            f"Nutzungsdauer angeben für „{name}“: der Betrag liegt über der GWG-Grenze von "
            f"{limit} für {bought}"
        )
    if above_limit(purchase) and purchase.input.date.year != bought:
        return f"Das Datum der Anschaffung von „{name}“ muss in {bought} liegen (für die AfA)"
    return None


def depreciation(purchase: "WorkEquipment", year: int) -> Depreciation | str | None:
    """Was `purchase` in `year` zählt; `None`, wenn nichts (noch nicht angeschafft, voll in einem
    früheren Jahr oder AfA vorbei); Text: warum es noch nicht feststeht."""
    bought = purchase.year
    if year < bought or year > bought + MAX_USEFUL_LIFE:
        return None
    above = above_limit(purchase)
    if above is None:
        return f"GWG-Grenze für {bought} noch nicht geprüft"
    if gap := missing(purchase):
        return gap
    cents = purchase.input.amount_cents
    if in_full(purchase):
        return Depreciation(cents) if year == bought else None
    life = counted_useful_life(purchase)
    assert life is not None  # sonst hätte `missing` sie angefordert
    return linear(cents, purchase.input.date, life * MONTHS, year)
