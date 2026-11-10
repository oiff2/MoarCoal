"""PROTOTYP – wegwerfen. Fake-Modul Steuerjahr: verbraucht die Schuldzinsen der Immobilie.

Zwei Arten zu verbrauchen:
1. Als Ausgewiesener Wert mit Kette (tax_year.rental_interest_total): Verweis-Posten.
2. Als Seite (anlage_v_rows): fragt Values direkt, macht nur die Zeilenzuordnung.
Steuerjahr importiert nichts aus immobilie.py, es kennt nur den Schlüssel als Text.
"""

from __future__ import annotations

from dataclasses import dataclass

from datenebene import (
    Calculation,
    CatalogEntry,
    ExposedValue,
    ModuleKey,
    ModuleRegistration,
    Money,
    NotYetComputable,
    Period,
    Unit,
    UserId,
    ValueDefinition,
    ValueKey,
    Values,
)

KEY = ModuleKey("tax_year")
RENTAL_INTEREST_TOTAL = ValueKey("tax_year.rental_interest_total")
PROPERTY_LOAN_INTEREST = ValueKey("property.loan_interest")  # nur der Text, kein Import


@dataclass
class TaxYearData:
    pass  # für die Skizze nicht nötig


def compute_rental_interest_total(calc: Calculation[TaxYearData]) -> Money:
    total = Money(0)
    for s in calc.subjects_of(PROPERTY_LOAN_INTEREST):
        li = calc.use(PROPERTY_LOAN_INTEREST, subject_id=s.id)  # fehlt einer → ganzer Wert noch nicht berechenbar
        assert isinstance(li.amount, Money)
        total += li.amount
    calc.step("Summe Schuldzinsen aller vermieteten Objekte", total)
    return total


def anlage_v_rows(values: Values, user: UserId, year: int) -> list[tuple[str, str, str]]:
    """Verbraucher außerhalb einer Rechnung: Seite „Anlage V“ je Objekt."""
    rows = []
    for subject, out in values.get(PROPERTY_LOAN_INTEREST, user, Period.year(year)).items():
        name = subject.display_name if subject else "–"
        match out:
            case ExposedValue():
                rows.append((name, "Schuldzinsen (Zeile fiktiv)", f"{out.amount}  [{out.backing}]"))
            case NotYetComputable():
                rows.append((name, "Schuldzinsen (Zeile fiktiv)", f"noch nicht berechenbar: {out.reason}"))
    return rows


REGISTRATION: ModuleRegistration[TaxYearData] = ModuleRegistration(
    key=KEY,
    display_name="Steuerjahr",
    empty_data=TaxYearData,
    values=[
        ValueDefinition(
            CatalogEntry(RENTAL_INTEREST_TOTAL, "Schuldzinsen aller vermieteten Objekte", Unit.EUR, Period, False),
            compute_rental_interest_total,
        ),
    ],
)
