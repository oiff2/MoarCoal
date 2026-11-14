"""Baustein Angaben zur Person: Vorname und Name (docs/grundgeruest.md, 3.2; ADR 0009)."""

from collections.abc import Mapping

from pydantic import Field, field_validator

from moarcoal.storage.entries import Entry, EntryAddress, entry_kind

PERSONAL_DETAILS_SCHEMA = "datenebene/1"


class PersonalDetails(Entry):
    """Vorname und Name des Nutzers, genau eine Eintragung je Nutzer (`owner`).

    `issuer` verweist auf den eigenen Aussteller („Vorname Name“, Privatperson), den die App beim
    Speichern anlegt und gleichhält. Der Name ist hier nicht sensibel markiert: in die Sperrliste
    gelangt er nur über den Aussteller.
    """

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    issuer: EntryAddress | None = None

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


def check_personal_details(
    details: PersonalDetails, entries: Mapping[EntryAddress, Entry]
) -> str | None:
    """Prüfung im Schreibweg: genau eine je Nutzer, der Aussteller (falls genannt) ist ein
    vorhandener Aussteller."""
    if any(
        isinstance(e, PersonalDetails) and e.owner == details.owner and e.id != details.id
        for e in entries.values()
    ):
        return "Angaben zur Person gibt es schon."
    if details.issuer is not None and (
        details.issuer.kind != "Issuer" or details.issuer not in entries
    ):
        return "Aussteller existiert nicht."
    return None


PERSONAL_DETAILS_KIND = entry_kind(
    PersonalDetails,
    PERSONAL_DETAILS_SCHEMA,
    personal_details_path,
    check=check_personal_details,
)
