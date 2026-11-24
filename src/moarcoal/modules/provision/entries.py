"""Steuerliche Bedeutung eines Vertrags: ein eigener Eintrag des Moduls, der auf den Vertrag
verweist (der Vertrag selbst ist ein Baustein der Datenebene und weiß davon nichts)."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from moarcoal.modules.provision.common import SCHEMA
from moarcoal.storage import Agreement, Entry, EntryAddress, EntryKind, entry_kind


class TaxMeaning(StrEnum):
    """Was ein Vertrag für die Anlage Vorsorgeaufwand ist (genau eine je Vertrag oder keine)."""

    PRIVATE_HEALTH_CARE = "private_health_care"
    BASIC_PENSION = "basic_pension"
    ACCIDENT_LIABILITY_RISK = "accident_liability_risk"
    DISABILITY = "disability"
    UNEMPLOYMENT = "unemployment"

    @property
    def label(self) -> str:
        return MEANING_LABELS[self]


MEANING_LABELS: dict[TaxMeaning, str] = {
    TaxMeaning.PRIVATE_HEALTH_CARE: "Kranken- und Pflegeversicherung privat",
    TaxMeaning.BASIC_PENSION: "Basisrente",
    TaxMeaning.ACCIDENT_LIABILITY_RISK: "Unfall/Haftpflicht/Risiko",
    TaxMeaning.DISABILITY: "Berufsunfähigkeit",
    TaxMeaning.UNEMPLOYMENT: "Arbeitslosigkeit",
}


class AgreementMeaning(Entry):
    """Die Steuerliche Bedeutung eines Vertrags des Nutzers; je Vertrag höchstens ein Eintrag.

    Der Eintrag fällt mit dem Vertrag weg (`EntryKind.falls_with`): löscht man den Vertrag, räumt
    der Vorgang die Bedeutung mit ab.
    """

    agreement: EntryAddress
    meaning: TaxMeaning

    @model_validator(mode="after")
    def _agreement_is_an_agreement(self) -> Self:
        if self.agreement.kind != Agreement.__name__:
            raise ValueError("Vertrag verweist nicht auf einen Vertrag")
        return self


def check_meaning(meaning: AgreementMeaning, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Prüfung im Schreibweg: der Vertrag ist ein vorhandener Vertrag desselben Nutzers, und er
    hat keine zweite Bedeutung."""
    agreement = entries.get(meaning.agreement)
    if not isinstance(agreement, Agreement) or agreement.owner != meaning.owner:
        return "Vertrag existiert nicht."
    if any(
        isinstance(e, AgreementMeaning) and e.id != meaning.id and e.agreement == meaning.agreement
        for e in entries.values()
    ):
        return "Dieser Vertrag hat schon eine Steuerliche Bedeutung."
    return None


KINDS: tuple[EntryKind, ...] = (
    entry_kind(
        AgreementMeaning,
        SCHEMA,
        lambda entry: f"users/{entry.owner}/provision/meanings.json",
        check=check_meaning,
        falls_with="agreement",
        label="Steuerliche Bedeutung",
    ),
)
