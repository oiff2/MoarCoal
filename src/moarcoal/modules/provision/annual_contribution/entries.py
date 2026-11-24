"""Jahresbeitrag: Eintragsart des Moduls Vorsorge, von Hand auf der Seite Vorsorge erfasst."""

from collections.abc import Mapping
from typing import Self

from pydantic import Field, model_validator

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.provision.common import SCHEMA, yearly_path
from moarcoal.modules.provision.entries import AgreementMeaning
from moarcoal.storage import Agreement, Document, Entry, EntryAddress, EntryKind, entry_kind

MAX_CENTS = 100_000_000_000  # 1 Mrd. Euro


class AnnualContribution(Entry):
    """Betrag, den der Nutzer im Jahr `year` auf den Vertrag `agreement` gezahlt hat, und auf
    Wunsch die Erstattung (`None`: keine angegeben) und das Dokument als Beleg.

    Ein Betrag von 0 ist ein Wert (ausdrücklich nichts gezahlt), kein Fehlen. Das Jahr ist das der
    Zahlung (Zuflussprinzip). Höchstens einer je Vertrag und Jahr, der Vertrag gehört dem Nutzer
    und hat eine Steuerliche Bedeutung (`check_contribution` im Schreibweg). Der Eintrag fällt mit
    dem Vertrag weg; das Dokument sperrt dessen Löschen, solange der Eintrag auf es verweist.
    """

    agreement: EntryAddress
    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    amount_cents: int = Field(ge=0, le=MAX_CENTS)
    refund_cents: int | None = Field(default=None, ge=0, le=MAX_CENTS)
    document: EntryAddress | None = None

    @model_validator(mode="after")
    def _addresses_point_at_the_right_kinds(self) -> Self:
        if self.agreement.kind != Agreement.__name__:
            raise ValueError("Vertrag verweist nicht auf einen Vertrag")
        if self.document is not None and self.document.kind != Document.__name__:
            raise ValueError("Beleg verweist nicht auf ein Dokument")
        return self


def check_contribution(
    contribution: AnnualContribution, entries: Mapping[EntryAddress, Entry]
) -> str | None:
    """Prüfung im Schreibweg: der Vertrag ist ein vorhandener Vertrag desselben Nutzers mit
    Steuerlicher Bedeutung, der Beleg ein Dokument desselben Nutzers, und es gibt für Vertrag und
    Jahr keinen zweiten Jahresbeitrag."""
    agreement = entries.get(contribution.agreement)
    if not isinstance(agreement, Agreement) or agreement.owner != contribution.owner:
        return "Vertrag existiert nicht."
    if not any(
        isinstance(e, AgreementMeaning) and e.agreement == contribution.agreement
        for e in entries.values()
    ):
        return "Der Vertrag hat keine Steuerliche Bedeutung."
    if contribution.document is not None:
        document = entries.get(contribution.document)
        if not isinstance(document, Document) or document.owner != contribution.owner:
            return "Das zugeordnete Dokument gibt es nicht."
    if any(
        isinstance(e, AnnualContribution)
        and e.id != contribution.id
        and (e.agreement, e.year) == (contribution.agreement, contribution.year)
        for e in entries.values()
    ):
        return f"Für diesen Vertrag gibt es für {contribution.year} schon einen Jahresbeitrag."
    return None


KINDS: tuple[EntryKind, ...] = (
    entry_kind(
        AnnualContribution,
        SCHEMA,
        yearly_path,
        check=check_contribution,
        falls_with="agreement",
        label="Jahresbeitrag",
    ),
)
