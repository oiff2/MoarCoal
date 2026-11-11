"""Datentypen des Ausgewiesenen Werts: Betrag, Einheit, Zeitbezug, Fundstelle, Belegstand."""

import datetime
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import ClassVar, Self

from moarcoal.storage import EntryAddress


class Unit(StrEnum):
    """Einheit je Schlüssel aus fester Liste; der Wert ist die Anzeige."""

    EUR = "EUR"
    DAYS = "Tage"
    KM = "km"
    SQM = "m²"
    PERCENT = "Prozent"


@dataclass(frozen=True)
class Amount:
    """Eine Zahl mit Einheit. Geld liegt in Euro als `Decimal` vor; gerundet wird im Modul."""

    value: Decimal
    unit: Unit

    @classmethod
    def eur_cents(cls, cents: int) -> Self:
        return cls(Decimal(cents) / 100, Unit.EUR)

    @classmethod
    def of(cls, value: int | Decimal, unit: Unit) -> Self:
        return cls(Decimal(value), unit)


@dataclass(frozen=True)
class Period:
    """Zeitraum von `start` bis `end` einschließlich, meist ein Kalenderjahr."""

    start: datetime.date
    end: datetime.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("Zeitraum endet vor seinem Beginn")

    @classmethod
    def year(cls, year: int) -> Self:
        return cls(datetime.date(year, 1, 1), datetime.date(year, 12, 31))

    @property
    def calendar_year(self) -> int | None:
        """Das Jahr, wenn der Zeitraum genau ein Kalenderjahr ist, sonst `None`."""
        if self == Period.year(self.start.year):
            return self.start.year
        return None


@dataclass(frozen=True)
class KeyDate:
    """Stichtag eines Stichtagswerts."""

    day: datetime.date

    @classmethod
    def year_end(cls, year: int) -> Self:
        return cls(datetime.date(year, 12, 31))


type TimeRef = Period | KeyDate


class Backing(IntEnum):
    """Belegstand; die Ordnung ist die Stärke: ausstehend < angenommen < belegt."""

    PENDING = 1  # ausstehend
    ASSUMED = 2  # angenommen
    PROVEN = 3  # belegt

    @property
    def label(self) -> str:
        return {1: "ausstehend", 2: "angenommen", 3: "belegt"}[self.value]


class Locator:
    """Fundstelle eines Einzelposten. Aus ihrer Art ergibt sich der Belegstand."""

    @property
    def label(self) -> str:
        raise NotImplementedError

    @property
    def entry_address(self) -> EntryAddress | None:
        """Der Eintrag, auf den die Fundstelle zeigt, falls sie auf einen zeigt."""
        return None

    @property
    def backing(self) -> Backing:
        raise NotImplementedError


@dataclass(frozen=True)
class UserInputLocator(Locator):
    """Nutzereingabe, genannt über die Adresse ihres Eintrags: Belegstand angenommen."""

    address: EntryAddress

    @property
    def label(self) -> str:
        return "Nutzereingabe"

    @property
    def entry_address(self) -> EntryAddress | None:
        return self.address

    @property
    def backing(self) -> Backing:
        return Backing.ASSUMED


@dataclass(frozen=True)
class LineItem:
    """Zahl mit eigener Einheit und genau einer Fundstelle; der Belegstand kommt von ihr."""

    label: str
    amount: Amount
    locator: Locator

    @property
    def backing(self) -> Backing:
        return self.locator.backing


@dataclass(frozen=True)
class WorkingStep:
    """Ein Schritt des Rechenwegs: Einzelposten, Zwischenergebnis oder Entscheidung."""

    kind: str  # "item", "step" oder "decision"
    text: str
    amount: Amount | None = None


@dataclass(frozen=True)
class Workings:
    """Rechenweg: die festgehaltene Folge der Schritte einer Rechnung."""

    steps: tuple[WorkingStep, ...]


KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class ValueKey(str):
    """Schlüssel im Wertekatalog: `<modulschlüssel>.<name>`, z. B. `work.workdays`."""

    def __new__(cls, text: str) -> Self:
        if not KEY_PATTERN.match(text):
            raise ValueError(f"kein Schlüssel der Form <modul>.<name>: {text!r}")
        return super().__new__(cls, text)

    @property
    def module(self) -> str:
        return self.partition(".")[0]


@dataclass(frozen=True)
class Subject:
    """Bezugsobjekt: der Eintrag, auf den sich ein Wert bezieht."""

    address: EntryAddress


@dataclass(frozen=True)
class ExposedValue:
    """Ein Ausgewiesener Wert mit Betrag, Einzelposten und Rechenweg."""

    outcome: ClassVar[str] = "amount"

    key: ValueKey
    user: str
    time: TimeRef
    subject: Subject | None
    amount: Amount
    items: tuple[LineItem, ...]
    workings: Workings

    @property
    def backing(self) -> Backing:
        """Schwächster Belegstand der Einzelposten; ohne Einzelposten belegt."""
        return min((item.backing for item in self.items), default=Backing.PROVEN)


@dataclass(frozen=True)
class NotYetComputable:
    """Dem Wert fehlt ein Einzelposten, dessen Fehlen die Rechnung nicht regelt."""

    outcome: ClassVar[str] = "not_yet"

    key: ValueKey
    user: str
    time: TimeRef
    subject: Subject | None
    reason: str


@dataclass(frozen=True)
class NotApplicable:
    """Der Wert trifft fachlich nicht zu (ausdrückliche Entscheidung der Rechnung)."""

    outcome: ClassVar[str] = "not_applicable"

    key: ValueKey
    user: str
    time: TimeRef
    subject: Subject | None
    reason: str


type ValueResult = ExposedValue | NotYetComputable | NotApplicable
