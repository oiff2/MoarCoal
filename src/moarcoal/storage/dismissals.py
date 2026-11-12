"""Baustein Ausblendung: ein Nutzer blendet einen Befund mit Notiz aus (Spec 3.2)."""

import datetime

from pydantic import Field, field_validator

from moarcoal.storage.entries import Entry, entry_kind

DISMISSAL_SCHEMA = "datenebene/1"


class Dismissal(Entry):
    """Eine Ausblendung: Befundart, Ziel (als Text) und Fingerabdruck des Befunds, dazu die
    Pflicht-Notiz mit Datum. Sie gilt nur für den Eigentümer und nur, solange Befundart, Ziel und
    Fingerabdruck eines Befunds alle gleich sind; sonst kommt der Befund zurück.
    """

    finding_kind: str = Field(min_length=1)
    target: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    note: str = Field(min_length=1)
    noted_on: datetime.date

    @field_validator("note")
    @classmethod
    def _note_is_not_blank(cls, note: str) -> str:
        if not note.strip():
            raise ValueError("Die Notiz darf nicht leer sein")
        return note


def dismissal_path(entry: Dismissal) -> str:
    return f"users/{entry.owner}/dismissals.json"


DISMISSAL_KIND = entry_kind(Dismissal, DISMISSAL_SCHEMA, dismissal_path)
