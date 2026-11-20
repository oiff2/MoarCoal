"""AfA der Arbeitsmittel: was eine Anschaffung in einem Steuerjahr zur Summe beiträgt.

Hier stehen nur die Regeln der Arbeitsmittel (GWG-Grenze je Jahr, Nutzungsdauer in Jahren, ein
Jahr voll nach BMF); gerechnet wird mit dem Baustein `values.depreciation`. Rechtslage und Quellen:
`docs/recherche-arbeitsmittel-afa.md`. Die Rechnung des Werts, der Schreibweg und die Seite nutzen
diese Funktionen gleich.
"""

from typing import TYPE_CHECKING

from moarcoal.values.depreciation import MONTHS, Depreciation, linear

if TYPE_CHECKING:  # die Eintragsart prüft mit diesen Funktionen, daher kein Import zur Laufzeit
    from moarcoal.modules.work.workplace.entries import WorkEquipment

MAX_USEFUL_LIFE = 30  # Jahre; länger hält kein Arbeitsmittel (AfA-Tabellen: Möbel 13 Jahre)

# GWG-Grenze je Steuerjahr der Anschaffung, brutto in Cent: 800 € ohne Umsatzsteuer
# (§ 9 Abs. 1 Satz 3 Nr. 7 Satz 2 i. V. m. § 6 Abs. 2 Satz 1 EStG) mit 19 % Umsatzsteuer.
# Nur geprüfte Jahre; ein neues Jahr wird geprüft und mit Quelle nachgetragen, nie fortgeschrieben.
GWG_LIMITS: dict[int, int] = dict.fromkeys(range(2018, 2027), 95_200)
GWG_SOURCE = "§ 6 Abs. 2 EStG, geprüft am 20.11.2026 (docs/recherche-arbeitsmittel-afa.md)"


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
    return linear(cents, purchase.input.date, life * MONTHS, year)
