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
    fest, dass die Bescheinigung eine Angabe nicht nennt (Nr. 17, 18, 24 a, 25 und 26).

    Nr. 22 bis 24 und 27 (Beiträge zur Vorsorge) nennt sie nur, soweit die Einlese-Regel den Pfad
    kennt: 22 a/b, 23 a/b, 24 b, 24 c und 27. Nr. 24 a, 25 und 26 liest sie noch nicht (Pfad
    unbekannt; sie gelten ohne unbekannte Pfade als nicht bescheinigt).
    """

    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    tax_class: int | None = Field(default=None, ge=1, le=6)
    gross_wages_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    income_tax_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    soli_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)
    employer_pension_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)  # Nr. 22 a/b
    employee_pension_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)  # Nr. 23 a/b
    subsidy_private_health_cents: int | None = Field(  # Nr. 24 b
        default=None, ge=0, le=MAX_WAGE_CENTS
    )
    subsidy_care_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)  # Nr. 24 c
    unemployment_cents: int | None = Field(default=None, ge=0, le=MAX_WAGE_CENTS)  # Nr. 27
    places: dict[str, str] = Field(default_factory=dict)
    unrecognized: list[str] = Field(default_factory=list)


KINDS: tuple[EntryKind, ...] = (
    entry_kind(WageTaxCertificate, SCHEMA, yearly_path, falls_with="document", label="Einlesung"),
)
