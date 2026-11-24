"""Anbieterbescheinigung Basisrente: das Ergebnis des Einlesens (eDaten)."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.provision.common import SCHEMA, yearly_path
from moarcoal.modules.provision.health_certificate.entries import MAX_CONTRIBUTION_CENTS, TEXT_MAX
from moarcoal.storage import MIN_DENYLIST_LENGTH, EntryKind, ReadInEntry, entry_kind
from moarcoal.storage.agreements import NUMBER_MAX


class PensionLine(BaseModel):
    """Ein Beitragsblock der Datei: das Zahljahr und der Betrag in Cent. `place` ist die
    Fundstelle des Betrags: der volle Feldname `data-name`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    paid_year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    cents: int = Field(ge=0, le=MAX_CONTRIBUTION_CENTS)
    place: str = Field(min_length=1, max_length=TEXT_MAX)


class BasicPensionCertificate(ReadInEntry):
    """Ergebnis des Einlesens einer Anbieterbescheinigung Basisrente (eDaten) zu genau einem
    Dokument.

    `year` ist das Zahljahr (Zuflussprinzip), `contract_number` die Vertragsnummer wörtlich aus
    der Datei (sensibel: Sperrliste, nie in Neueinlesung, Meldung oder Befund),
    `certification_number` die Zertifizierungsnummer des Vertrags, wenn die Datei sie nennt.
    `lines` sind die Beitragsblöcke in der Reihenfolge der Datei; was die Datei nicht nennt, steht
    nicht da (nie 0). `unrecognized` nennt die Pfade der Datei, die die Einlese-Regel nicht kennt;
    solange welche da sind, ist offen, ob ein Betrag darunter ist. Die Bescheinigung fällt mit dem
    Dokument weg.
    """

    sensitive_fields: ClassVar[frozenset[str]] = frozenset({"contract_number"})

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    contract_number: str = Field(min_length=1, max_length=NUMBER_MAX)
    certification_number: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    lines: tuple[PensionLine, ...] = ()
    unrecognized: list[str] = Field(default_factory=list)


def denylist_lines(certificates: list[BasicPensionCertificate]) -> list[str]:
    """Sperrlistenwerte der Bescheinigungen: die Vertragsnummern ab 6 Zeichen, ganz (Spec 8)."""
    found = {
        number
        for certificate in certificates
        if len(number := certificate.contract_number.strip()) >= MIN_DENYLIST_LENGTH
    }
    return sorted(found)


KINDS: tuple[EntryKind, ...] = (
    entry_kind(
        BasicPensionCertificate,
        SCHEMA,
        yearly_path,
        falls_with="document",
        denylist=denylist_lines,
        label="Einlesung",
    ),
)
