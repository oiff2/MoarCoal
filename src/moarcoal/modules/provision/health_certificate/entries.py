"""Beitragsbescheinigung Kranken-/Pflegeversicherung: das Ergebnis des Einlesens (eDaten)."""

import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.provision.common import SCHEMA, yearly_path
from moarcoal.storage import EntryKind, ReadInEntry, entry_kind

MAX_CONTRIBUTION_CENTS = 100_000_000_000  # 1 Mrd. Euro
TEXT_MAX = 500


class ContributionKind(StrEnum):
    """Was ein Beitragsposten ist, soweit MoarCoal die `BetragArt` der Datei kennt."""

    HEALTH_BASIC = "health_basic"  # Krankenversicherung, Basisleistungen (Z. 23)
    CARE = "care"  # Pflege-Pflichtversicherung (Z. 24)
    HEALTH_REFUND = "health_refund"  # erstattete Beiträge zur Krankenversicherung (Z. 25)
    CARE_REFUND = "care_refund"  # erstattete Beiträge zur Pflege-Pflichtversicherung (Z. 25)


class Characteristic(StrEnum):
    """`MerkmalBeiTrag`: wie der Beitrag versichert ist."""

    PRIVATE = "private"
    STATUTORY = "statutory"


class ContributionLine(BaseModel):
    """Ein Block `Vertragsdaten-Beitragsdaten` der Datei, roh bis auf den Betrag in Cent.

    `art` ist die `BetragArt` wörtlich; `kind` ist `None`, wenn MoarCoal sie nicht kennt (der
    Wert gilt dann als noch nicht berechenbar). Ebenso `characteristic` für ein `MerkmalBeiTrag`,
    das weder privat noch gesetzlich ist (`merkmal` hält es wörtlich). `place` ist die Fundstelle
    des Betrags: der volle Feldname `data-name`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    art: str = Field(min_length=1, max_length=TEXT_MAX)
    kind: ContributionKind | None
    merkmal: str = Field(max_length=TEXT_MAX)
    characteristic: Characteristic | None
    cents: int = Field(ge=0, le=MAX_CONTRIBUTION_CENTS)
    start: datetime.date | None = None
    end: datetime.date | None = None
    place: str = Field(min_length=1, max_length=TEXT_MAX)


class HealthContributionCertificate(ReadInEntry):
    """Ergebnis des Einlesens einer Beitragsbescheinigung Kranken-/Pflegeversicherung (eDaten) zu
    genau einem Dokument.

    `year` ist das Jahr der Zahlung oder Erstattung laut Datei (Zuflussprinzip). `lines` sind ihre
    Blöcke in der Reihenfolge der Datei; was die Datei nicht nennt, steht nicht da (nie 0).
    `unrecognized` nennt die Pfade der Datei, die die Einlese-Regel nicht kennt; solange welche
    da sind, ist offen, ob ein Betrag darunter ist. Die Bescheinigung fällt mit dem Dokument weg;
    nach dem Löschen lässt sich die Datei erneut aufnehmen und wird neu eingelesen.
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    lines: tuple[ContributionLine, ...] = ()
    unrecognized: list[str] = Field(default_factory=list)


KINDS: tuple[EntryKind, ...] = (
    entry_kind(
        HealthContributionCertificate,
        SCHEMA,
        yearly_path,
        falls_with="document",
        label="Einlesung",
    ),
)
