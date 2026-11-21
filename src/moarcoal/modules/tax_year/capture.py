"""Woraus ein Feld rechnet: die fremden Werte im Ergebnis eines Felds (#176, #180).

Das Steuerjahr kennt die anderen Module nicht. Es liest die Schlüssel zur Laufzeit aus dem
Ergebnis: bei einem Betrag aus den Einzelposten, die einen anderen Wert verwenden, bei „noch
nicht berechenbar“ aus der Kette. Eigene Werte (Schlüssel des Steuerjahrs) werden bis zum ersten
fremden verfolgt; wohin dessen Erfassung führt, sagt das Modul, dem er gehört.
"""

from moarcoal.modules.tax_year.entries import MODULE_KEY
from moarcoal.values.model import ExposedValue, NotYetComputable, ValueRef

_OWN = f"{MODULE_KEY}."


def _own(ref: ValueRef) -> bool:
    return ref.key.startswith(_OWN)


def foreign_refs(result: object) -> list[ValueRef]:
    """Die ersten fremden Werte, auf die sich das Ergebnis stützt, in Reihenfolge, je einmal."""
    found: list[ValueRef] = []

    def add(ref: ValueRef) -> None:
        if ref not in found:
            found.append(ref)

    def walk(value: ExposedValue) -> None:
        for item in value.items:
            used = item.locator.used_value
            if used is None:
                continue
            if _own(used.ref):
                walk(used)
            else:
                add(used.ref)

    if isinstance(result, ExposedValue):
        walk(result)
    elif isinstance(result, NotYetComputable):
        first = next((ref for ref in result.chain if not _own(ref)), None)
        if first is not None:
            add(first)
    return found
