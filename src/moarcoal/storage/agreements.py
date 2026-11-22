"""Baustein Vertrag: eine Vereinbarung mit einem Aussteller als Vertragspartner (Spec 3.2)."""

import datetime
from collections.abc import Mapping
from typing import Self

from pydantic import Field, field_validator, model_validator

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind
from moarcoal.storage.issuers import MIN_DENYLIST_LENGTH, Issuer, name_key

AGREEMENT_SCHEMA = "datenebene/1"
NAME_MAX = 200
NUMBER_MAX = 100
CATEGORIES = ("Versicherung", "Darlehen", "Depot", "Konto", "Sonstiges")
"""Die Arten eines Vertrags; neue Werte kommen hier im Code dazu, nicht über die Oberfläche."""


class Agreement(Entry):
    """Ein Vertrag des Nutzers: `issuer` ist der Vertragspartner, `name` die Bezeichnung (der
    Anzeigename), `number` die Vertragsnummer (sensibel), `category` die Art (einer der
    `CATEGORIES`; die Prüfung im Schreibweg weist anderes ab). Beginn und Ende sind optional;
    ohne Ende läuft der Vertrag.

    Was der Vertrag steuerlich bedeutet, weiß das Modul; es verweist mit eigenen Einträgen auf ihn.
    """

    issuer: EntryAddress
    name: str = Field(min_length=1, max_length=NAME_MAX)
    number: str = Field(default="", max_length=NUMBER_MAX)
    category: str = "Sonstiges"
    start: datetime.date | None = None
    end: datetime.date | None = None

    @field_validator("name")
    @classmethod
    def _name_is_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bezeichnung ist leer")
        return value

    @model_validator(mode="after")
    def _issuer_is_an_issuer(self) -> Self:
        if self.issuer.kind != Issuer.__name__:
            raise ValueError("Vertragspartner verweist nicht auf einen Aussteller")
        return self

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.start and self.end and self.end < self.start:
            raise ValueError("Laufzeit endet vor ihrem Beginn")
        return self

    @property
    def display_name(self) -> str:
        return self.name

    def sensitive_values(self) -> list[str]:
        """Die Werte für die Sperrliste: die Vertragsnummer."""
        return [self.number] if self.number.strip() else []


def agreement_path(entry: Agreement) -> str:
    return f"users/{entry.owner}/agreements.json"


def denylist_lines(agreements: list[Agreement]) -> list[str]:
    """Sperrlistenwerte der Verträge: die Vertragsnummern ab 6 Zeichen, ganz (Spec 8)."""
    found = {
        value.strip()
        for agreement in agreements
        for value in agreement.sensitive_values()
        if len(value.strip()) >= MIN_DENYLIST_LENGTH
    }
    return sorted(found)


def _number_key(number: str) -> str:
    return number.strip().casefold()


def check_agreement(agreement: Agreement, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Prüfung im Schreibweg: die Art steht in der Liste, der Vertragspartner ist ein vorhandener
    Aussteller, und der Nutzer hat bei diesem Vertragspartner keinen zweiten Vertrag gleicher
    Bezeichnung oder, wenn vorhanden, gleicher Vertragsnummer (Groß/klein egal)."""
    if agreement.category not in CATEGORIES:
        return f"Art muss eine von {', '.join(CATEGORIES)} sein."
    if not isinstance(entries.get(agreement.issuer), Issuer):
        return "Vertragspartner existiert nicht."
    others = [
        e
        for e in entries.values()
        if isinstance(e, Agreement)
        and e.id != agreement.id
        and (e.owner, e.issuer) == (agreement.owner, agreement.issuer)
    ]
    if any(name_key(e.name) == name_key(agreement.name) for e in others):
        return "Diesen Vertrag gibt es schon."
    number = _number_key(agreement.number)
    if number and any(_number_key(e.number) == number for e in others):
        return "Diese Vertragsnummer gibt es bei diesem Vertragspartner schon."
    return None


AGREEMENT_KIND = entry_kind(
    Agreement,
    AGREEMENT_SCHEMA,
    agreement_path,
    check=check_agreement,
    denylist=denylist_lines,
    label="Vertrag",
)
