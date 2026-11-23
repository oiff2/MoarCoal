"""Baustein Aussteller: wer ein Dokument ausgestellt hat (docs/grundgeruest.md, 3.2)."""

from collections.abc import Callable, Iterable, Mapping
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from moarcoal.storage.entries import Entry, EntryAddress, EntryKind, entry_kind
from moarcoal.storage.hidden_files import COMMON_OWNER

ISSUER_SCHEMA = "datenebene/1"
MIN_DENYLIST_LENGTH = 6  # kürzere Werte und Teile fängt die Sperrliste nicht ab (Spec 8)


def name_key(text: str) -> str:
    """Vergleichsform von Namen und Aliassen: ohne Groß-/Kleinschreibung und Randleerzeichen."""
    return text.strip().casefold()


def portal_problem(text: str) -> str | None:
    """Warum `text` kein Portal sein kann (nur eine Adresse mit http oder https und Rechnername,
    ohne Leerraum), sonst `None`."""
    if text != text.strip() or any(c.isspace() for c in text):
        return "Portal enthält Leerraum"
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return "Portal ist keine gültige Adresse"
    if parts.scheme not in ("http", "https") or not host:
        return "Portal muss eine Adresse mit http oder https sein"
    return None


class Issuer(Entry):
    """Ein Aussteller im gemeinsamen Katalog: Name, weitere Namen (Aliasse), Privatperson, dazu
    optional Portal und Notiz.

    Nur bei einer Privatperson sind Name und Aliasse sensibel. Der Eigentümer ist immer
    `COMMON_OWNER`.
    """

    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    private_person: bool = False
    portal: str | None = None  # Adresse des Kundenportals, nur http(s)
    note: str | None = None  # freier Text, für alle Nutzer gleich
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

    @field_validator("portal")
    @classmethod
    def _portal_is_a_web_address(cls, value: str | None) -> str | None:
        if value is not None and (reason := portal_problem(value)):
            raise ValueError(reason)
        return value

    @field_validator("note")
    @classmethod
    def _note_is_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Notiz ist leer")
        return value

    @model_validator(mode="after")
    def _is_common(self) -> Self:
        if self.owner != COMMON_OWNER:
            raise ValueError("Aussteller gehören allen Nutzern")
        return self

    @property
    def display_name(self) -> str:
        return self.name

    def sensitive_values(self) -> list[str]:
        """Die Werte für die Sperrliste: Name und Aliasse, nur bei einer Privatperson."""
        return [self.name, *self.aliases] if self.private_person else []


def issuer_with_name(issuers: Iterable[Issuer], text: str) -> Issuer | None:
    """Der Aussteller, dessen Name oder Alias dem Text gleicht (nach `name_key`)."""
    key = name_key(text)
    return next((i for i in issuers if key in {name_key(n) for n in (i.name, *i.aliases)}), None)


def name_clashes(issuers: Iterable[Issuer]) -> set[str]:
    """Kennungen der Aussteller, deren Name oder Alias bei einem anderen Aussteller oder im
    eigenen Namen und Aliassen noch einmal vorkommt."""
    owners: dict[str, set[str]] = {}
    clashing: set[str] = set()
    for issuer in issuers:
        keys = [name_key(n) for n in (issuer.name, *issuer.aliases)]
        if len(set(keys)) < len(keys):
            clashing.add(issuer.id)
        for key in set(keys):
            owners.setdefault(key, set()).add(issuer.id)
    for ids in owners.values():
        if len(ids) > 1:
            clashing |= ids
    return clashing


def denylist_lines(issuers: list[Issuer]) -> list[str]:
    """Sperrlistenwerte der Aussteller: ganze Werte und Namensteile ab 6 Zeichen (Spec 8)."""
    found: set[str] = set()
    for issuer in issuers:
        for value in issuer.sensitive_values():
            for part in (value, *value.split()):
                if len(part) >= MIN_DENYLIST_LENGTH:
                    found.add(part)
    return sorted(found)


def check_issuer(issuer: Issuer, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Prüfung im Schreibweg: Portal nur http(s), Name und Aliasse kommen nach dem Vorgang nur
    einmal vor."""
    if issuer.portal is not None and (reason := portal_problem(issuer.portal)):
        return reason
    clashing = name_clashes(e for e in entries.values() if isinstance(e, Issuer))
    return "Name gibt es schon." if issuer.id in clashing else None


def merge_issuers(source: Issuer, target: Issuer) -> Issuer:
    """Das Ziel nach dem Zusammenführen: Name und Aliasse der Quelle werden Aliasse (ohne
    Dubletten), ihre Kennung löst auf das Ziel auf, Privatperson, wenn eine von beiden es war.
    Portal und Notiz des Ziels bleiben; fehlt dem Ziel das Portal, gilt das der Quelle, und eine
    andere Notiz der Quelle wird unter die des Ziels gesetzt."""
    notes = [n for n in (target.note, source.note) if n]
    note = "\n\n".join(dict.fromkeys(notes)) or None
    known = {name_key(n) for n in (target.name, *target.aliases)}
    added = [n for n in (source.name, *source.aliases) if name_key(n) not in known]
    return target.model_copy(
        update={
            "aliases": (*target.aliases, *dict.fromkeys(added)),
            "merged_ids": (*target.merged_ids, source.id, *source.merged_ids),
            "private_person": target.private_person or source.private_person,
            "portal": target.portal or source.portal,
            "note": note,
        }
    )


def issuer_path(entry: Issuer) -> str:
    return "common/issuers.json"


type IssuerCheck = Callable[[Issuer, Mapping[EntryAddress, Entry]], str | None]


def issuer_entry_kind(check_own: IssuerCheck | None = None) -> EntryKind:
    """Die Eintragsart Aussteller. `check_own` prüft im Schreibweg zusätzlich den eigenen
    Aussteller gegen die Angaben zur Person (`check_own_issuer`, ADR 0009)."""

    def check(issuer: Issuer, entries: Mapping[EntryAddress, Entry]) -> str | None:
        reason = check_issuer(issuer, entries)
        if reason is None and check_own is not None:
            reason = check_own(issuer, entries)
        return reason

    return entry_kind(
        Issuer,
        ISSUER_SCHEMA,
        issuer_path,
        check=check,
        denylist=denylist_lines,
        merge=merge_issuers,
        former_ids=lambda issuer: issuer.merged_ids,
    )
