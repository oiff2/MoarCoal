"""Baustein Angaben zur Person: Name, Stammdaten, Religionszugehörigkeit (docs/grundgeruest.md,
3.2; ADR 0009 samt Nachtrag)."""

import datetime
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind
from moarcoal.storage.identifiers import iban_problem, id_number_problem
from moarcoal.storage.issuers import Issuer, name_key

PERSONAL_DETAILS_SCHEMA = "datenebene/1"
TEXT_MAX = 200


class Religion(StrEnum):
    """Die Religionsgemeinschaft; `NONE` heißt keine oder keine, die Kirchensteuer erhebt."""

    NONE = "keine"
    EVANGELICAL = "evangelisch"
    ROMAN_CATHOLIC = "roemisch-katholisch"
    OLD_CATHOLIC = "altkatholisch"

    @property
    def levies_church_tax(self) -> bool:
        return self is not Religion.NONE


class ReligionMembership(BaseModel):
    """Die Religion ab einem Datum; sie gilt, bis eine spätere Angabe sie ablöst."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_date: datetime.date
    religion: Religion


class PersonalDetails(Entry):
    """Vorname, Name und die selten wechselnden Angaben des Nutzers, genau eine Eintragung je
    Nutzer (`owner`). Alle Angaben außer dem Namen sind freiwillig (`None`: noch nicht angegeben).
    In `religions` kommt ein Datum nur einmal vor (`check_personal_details`).

    `issuer` verweist auf den eigenen Aussteller („Vorname Name“, Privatperson), den die App beim
    Speichern anlegt und gleichhält. Der Name ist hier nicht sensibel markiert: in die Sperrliste
    gelangt er nur über den Aussteller.
    """

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    issuer: EntryAddress | None = None
    birth_date: datetime.date | None = None
    id_number: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    title: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    street: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    house_number: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    postal_code: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    city: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    iban: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    account_holder: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    religions: tuple[ReligionMembership, ...] = ()

    @field_validator("first_name", "last_name")
    @classmethod
    def _is_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name ist leer")
        return value

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def personal_details_path(entry: PersonalDetails) -> str:
    return f"users/{entry.owner}/personal_details.json"


OWN_ISSUER_RULE = (
    "Der eigene Aussteller trägt den Namen aus den Angaben zur Person und ist Privatperson."
)


def carries_person(issuer: Issuer, details: PersonalDetails) -> bool:
    """Ob der Aussteller als eigener taugt: Privatperson, der Name der Angaben ist sein Name oder
    ein Alias. So bleibt der Name in der Sperrliste, auch nach dem Zusammenführen (ADR 0009)."""
    names = {name_key(n) for n in (issuer.name, *issuer.aliases)}
    return issuer.private_person and name_key(details.display_name) in names


def check_own_issuer(issuer: Issuer, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Prüfung im Schreibweg für jeden Aussteller: ist er der eigene eines Nutzers, trägt er
    dessen Namen und ist Privatperson."""
    for details in entries.values():
        if (
            isinstance(details, PersonalDetails)
            and details.issuer == issuer.address
            and not carries_person(issuer, details)
        ):
            return OWN_ISSUER_RULE
    return None


def _fields_problem(details: PersonalDetails) -> str | None:
    """Prüfziffer der Identifikationsnummer, Prüfsumme der IBAN, ein Datum je Religionsangabe."""
    if details.id_number is not None and (problem := id_number_problem(details.id_number)):
        return problem
    if details.iban is not None and (problem := iban_problem(details.iban)):
        return problem
    return religion_dates_problem(details.religions)


def religion_dates_problem(history: tuple[ReligionMembership, ...]) -> str | None:
    dates = [r.from_date for r in history]
    return "Religion: je Datum nur eine Angabe" if len(set(dates)) < len(dates) else None


def sensitive_values(entries: list[PersonalDetails]) -> list[str]:
    """Die Werte für die Sperrliste: Identifikationsnummer und IBAN (der Name kommt über den
    Aussteller, ADR 0009)."""
    values = (v for d in entries for v in (d.id_number, d.iban))
    return sorted({v for v in values if v})


def check_personal_details(
    details: PersonalDetails, entries: Mapping[EntryAddress, Entry]
) -> str | None:
    """Prüfung im Schreibweg: genau eine je Nutzer, der Aussteller (falls genannt) ist ein
    vorhandener Aussteller, der den Namen trägt und Privatperson ist."""
    if any(
        isinstance(e, PersonalDetails) and e.owner == details.owner and e.id != details.id
        for e in entries.values()
    ):
        return "Angaben zur Person gibt es schon."
    if problem := _fields_problem(details):
        return problem
    if details.issuer is None:
        return None
    issuer = entries.get(details.issuer)
    if not isinstance(issuer, Issuer):
        return "Aussteller existiert nicht."
    return None if carries_person(issuer, details) else OWN_ISSUER_RULE


PERSONAL_DETAILS_KIND = entry_kind(
    PersonalDetails,
    PERSONAL_DETAILS_SCHEMA,
    personal_details_path,
    check=check_personal_details,
    denylist=sensitive_values,
)
