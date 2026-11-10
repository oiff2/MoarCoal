"""PROTOTYP – wegwerfen. Fake-Modul Immobilie: weist Schuldzinsen je Immobilie aus.

Aufteilung:
- Daten: Dataclasses, die die Datenebene lädt (echte Fassung: Pydantic + JSON).
- Fachkern: reine Funktionen ohne Calculation, ohne Speicher, einzeln testbar.
- Anbindung: compute_* übersetzt Fachkern-Ergebnisse in Einzelposten und Rechenweg.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datenebene import (
    Backing,
    Calculation,
    CatalogEntry,
    Locator,
    ModuleKey,
    ModuleRegistration,
    Money,
    Period,
    Subject,
    TimeRef,
    Unit,
    ValueDefinition,
    ValueKey,
)

KEY = ModuleKey("property")
LOAN_INTEREST = ValueKey("property.loan_interest")

# --- Daten -------------------------------------------------------------------


@dataclass
class InterestEntry:
    year: int
    amount: Money
    locator: Locator
    backing: Backing
    label: str


@dataclass
class Loan:
    id: str
    display_name: str
    interest: list[InterestEntry] = field(default_factory=list)


@dataclass
class Property:
    id: str
    display_name: str
    loans: list[Loan] = field(default_factory=list)


@dataclass
class PropertyData:
    properties: list[Property] = field(default_factory=list)


# --- Fachkern (rein) ---------------------------------------------------------


def interest_for_year(loan: Loan, year: int) -> list[InterestEntry]:
    return [e for e in loan.interest if e.year == year]


def find_property(data: PropertyData, property_id: str) -> Property:
    return next(p for p in data.properties if p.id == property_id)


# --- Anbindung an die Datenebene ----------------------------------------------


def list_properties(data: PropertyData, time: TimeRef) -> list[Subject]:
    """Wer zählt die Bezugsobjekte auf? Das Modul, dem der Schlüssel gehört."""
    return [Subject(p.id, p.display_name) for p in data.properties]


def compute_loan_interest(calc: Calculation[PropertyData]) -> Money:
    assert calc.subject
    prop = find_property(calc.data, calc.subject.id)
    if not prop.loans:
        calc.decide("Kein Darlehen auf dieser Immobilie: Schuldzinsen 0 €")  # ausdrücklich, nicht still
        return Money(0)
    total = Money(0)
    for loan in prop.loans:
        entries = interest_for_year(loan, calc.year)
        if not entries:
            calc.not_yet(f"{prop.display_name}: keine Zinsangabe für {loan.display_name} {calc.year}")
        for e in entries:
            total += calc.item(e.label, e.amount, e.locator, e.backing).amount  # type: ignore[assignment]
    calc.step("Summe Schuldzinsen", total)
    return total


REGISTRATION: ModuleRegistration[PropertyData] = ModuleRegistration(
    key=KEY,
    display_name="Immobilie",
    empty_data=PropertyData,
    values=[
        ValueDefinition(
            CatalogEntry(LOAN_INTEREST, "Gezahlte Schuldzinsen aller Darlehen einer Immobilie", Unit.EUR, Period, True),
            compute_loan_interest,
            list_properties,
        ),
    ],
)
