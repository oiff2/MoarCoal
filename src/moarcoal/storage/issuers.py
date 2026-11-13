"""Baustein Aussteller: wer ein Dokument ausgestellt hat (docs/grundgeruest.md, 3.2)."""

from typing import Self

from pydantic import Field, field_validator, model_validator

from moarcoal.storage.entries import Entry, entry_kind
from moarcoal.storage.hidden_files import COMMON_OWNER

ISSUER_SCHEMA = "datenebene/1"
MIN_DENYLIST_LENGTH = 6  # kürzere Werte und Teile fängt die Sperrliste nicht ab (Spec 8)


def issuer_url(issuer_id: str) -> str:
    return f"/aussteller/{issuer_id}"


class Issuer(Entry):
    """Ein Aussteller im gemeinsamen Katalog: Name, weitere Namen (Aliasse), Privatperson.

    Nur bei einer Privatperson sind Name und Aliasse sensibel. Der Eigentümer ist immer
    `COMMON_OWNER`.
    """

    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    private_person: bool = False
    merged_ids: tuple[str, ...] = ()  # Kennungen zusammengeführter Aussteller, lösen auf diesen auf

    @field_validator("name")
    @classmethod
    def _name_is_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name ist leer")
        return value

    @field_validator("aliases")
    @classmethod
    def _aliases_are_text(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not alias.strip() for alias in value):
            raise ValueError("Alias ist leer")
        return value

    @model_validator(mode="after")
    def _is_common(self) -> Self:
        if self.owner != COMMON_OWNER:
            raise ValueError("Aussteller gehören allen Nutzern")
        return self

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def url(self) -> str:
        return issuer_url(self.id)

    def sensitive_values(self) -> list[str]:
        """Die Werte für die Sperrliste: Name und Aliasse, nur bei einer Privatperson."""
        return [self.name, *self.aliases] if self.private_person else []


def denylist_lines(issuers: list[Issuer]) -> list[str]:
    """Sperrlistenwerte der Aussteller: ganze Werte und Namensteile ab 6 Zeichen (Spec 8)."""
    found: set[str] = set()
    for issuer in issuers:
        for value in issuer.sensitive_values():
            for part in (value, *value.split()):
                if len(part) >= MIN_DENYLIST_LENGTH:
                    found.add(part)
    return sorted(found)


def issuer_path(entry: Issuer) -> str:
    return "common/issuers.json"


ISSUER_KIND = entry_kind(Issuer, ISSUER_SCHEMA, issuer_path)
