"""Baustein Vorschlag: Ergebnis einer Auslesung an einem Dokument (docs/grundgeruest.md, 3.6)."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind

PROPOSAL_SCHEMA = "datenebene/1"

type Content = str | int | float | bool | None


class ProposalField(BaseModel):
    """Ein Feld des Vorschlags: ausgelesener Inhalt mit Stelle, daneben Bestätigung und Korrektur.

    Der ausgelesene Inhalt bleibt bei einer Korrektur stehen; `correction` ist der Inhalt, den der
    Nutzer an seine Stelle setzt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Content
    location: str
    confirmed: bool = False
    correction: str | None = None

    @property
    def content(self) -> Content:
        """Was gilt, sobald das Feld bestätigt ist: die Korrektur, sonst das Ausgelesene."""
        return self.value if self.correction is None else self.correction


class Proposal(Entry):
    """Vorschlag an einem Dokument: Felder der Auslese-Vorlage, Rohantwort, Fassung der Vorlage."""

    document: EntryAddress
    template_version: int = Field(ge=1)
    fields: dict[str, ProposalField]
    raw: str
    created_at: datetime.datetime

    @property
    def open_keys(self) -> list[str]:
        return [key for key, field in self.fields.items() if not field.confirmed]


def proposal_path(entry: Proposal) -> str:
    return f"users/{entry.owner}/proposals.json"


PROPOSAL_KIND = entry_kind(Proposal, PROPOSAL_SCHEMA, proposal_path)
