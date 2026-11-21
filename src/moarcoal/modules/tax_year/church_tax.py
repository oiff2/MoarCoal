"""Kirchensteuerzahlung: eine Zahlung oder Erstattung von Kirchensteuer, von Hand erfasst.

Eintragsart des Steuerjahrs. Sie zählt im Jahr ihres Datums (nicht im Jahr, für das sie geschuldet
war) und liefert die Beträge der Felder „gezahlt“ und „erstattet“ der Anlage Sonderausgaben.
"""

import datetime
from collections.abc import Mapping

from pydantic import Field, field_validator

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.tax_year.entries import SCHEMA, TEXT_MAX
from moarcoal.registration import ModuleState
from moarcoal.storage import Document, Entry, EntryAddress, EntryKind, entry_kind

MAX_CENTS = 100_000_000


class ChurchTaxPayment(Entry):
    """Datum, Betrag, gezahlt oder erstattet (`refunded`), Art der Leistung (Text) und auf Wunsch
    das Dokument dazu (Bescheid oder Kontoauszug). Das Dokument sperrt dessen Löschen, solange die
    Zahlung auf es verweist."""

    date: datetime.date
    amount_cents: int = Field(gt=0, le=MAX_CENTS)
    refunded: bool = False
    benefit_type: str = Field(min_length=1, max_length=TEXT_MAX)
    document: EntryAddress | None = None

    @field_validator("date")
    @classmethod
    def _supported_year(cls, day: datetime.date) -> datetime.date:
        if not MIN_YEAR <= day.year <= MAX_YEAR:
            raise ValueError(f"Jahr zwischen {MIN_YEAR} und {MAX_YEAR}")
        return day

    @property
    def year(self) -> int:
        """Das Steuerjahr, in dem die Zahlung zählt: das ihres Datums."""
        return self.date.year


def payments_in_year(state: ModuleState, year: int) -> list[ChurchTaxPayment]:
    """Die Zahlungen und Erstattungen des Nutzers im Jahr, nach Datum."""
    return sorted(
        (p for p in state.all(ChurchTaxPayment) if p.year == year), key=lambda p: (p.date, p.id)
    )


def check_payment(entry: ChurchTaxPayment, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Schreibweg: ein zugeordnetes Dokument gibt es und gehört dem Nutzer."""
    if entry.document is None:
        return None
    target = entries.get(entry.document)
    if not isinstance(target, Document) or target.owner != entry.owner:
        return "Das zugeordnete Dokument gibt es nicht"
    return None


def yearly_path(entry: ChurchTaxPayment) -> str:
    return f"users/{entry.owner}/tax_year/{entry.year}.json"


KIND: EntryKind = entry_kind(
    ChurchTaxPayment, SCHEMA, yearly_path, check=check_payment, label="Kirchensteuerzahlung"
)
