"""Lohnsteuerbescheinigung: das Ergebnis des Einlesens (eDaten) als Eintrag."""

from pydantic import Field

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.work.common import SCHEMA, yearly_path
from moarcoal.storage import EntryKind, ReadInEntry, entry_kind

MAX_WAGE_CENTS = 100_000_000_000  # 1 Mrd. Euro


class WageTaxCertificate(ReadInEntry):
    """Ergebnis des Einlesens einer Lohnsteuerbescheinigung (eDaten) zu genau einem Dokument.

    Beträge stehen in ganzen Cent, genau wie bescheinigt. `None` heißt: die Bescheinigung nennt die
    Angabe nicht (nie 0). `places` nennt je Angabe den vollen Feldnamen `data-name` als Fundstelle.
    Dokument und Fassung der Einlese-Regel trägt `ReadInEntry`. Die Bescheinigung fällt mit dem
    Dokument weg; nach dem Löschen lässt sich die Datei erneut aufnehmen und wird neu eingelesen.
    `unrecognized` nennt die Pfade der Datei, die die Einlese-Regel nicht kennt; nur ohne sie steht
    fest, dass die Bescheinigung eine Angabe nicht nennt (Nr. 17 und 18).
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    tax_class: int | None = Field(default=None, ge=1, le=6)
    gross_wages_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    income_tax_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    soli_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    places: dict[str, str] = Field(default_factory=dict)
    unrecognized: list[str] = Field(default_factory=list)


KINDS: tuple[EntryKind, ...] = (
    entry_kind(WageTaxCertificate, SCHEMA, yearly_path, falls_with="document", label="Einlesung"),
)
