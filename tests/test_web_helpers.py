"""Gemeinsame Formular- und Abweisungshelfer der Seiten (`web.py`)."""

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, Field

from moarcoal.storage import Entry, EntryAddress, ExpectedDocument, Issuer, Rejected
from moarcoal.storage.issuers import COMMON_OWNER
from moarcoal.web.helpers import entry_of, rejection_reasons, rejection_text, validated


class Lookup:
    def __init__(self, *entries: Entry) -> None:
        self.entries = {e.address: e for e in entries}

    def get(self, address: EntryAddress) -> Entry | None:
        return self.entries.get(address)


def issuer(name: str = "Beispielbank AG") -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name)


def test_entry_of_returns_the_entry_of_the_kind() -> None:
    found = issuer()
    assert entry_of(Lookup(found), Issuer, found.id) is found


@pytest.mark.parametrize("entry_id", ["gibt-es-nicht", "../kaputt", ""])
def test_entry_of_is_404_for_unknown_or_invalid_ids(entry_id: str) -> None:
    with pytest.raises(HTTPException) as caught:
        entry_of(Lookup(issuer()), Issuer, entry_id)
    assert caught.value.status_code == 404


def test_entry_of_is_404_for_a_foreign_owner_and_only_checks_when_asked() -> None:
    found = ExpectedDocument(owner="anna", document_kind="x", start_year=2024)
    lookup = Lookup(found)
    assert entry_of(lookup, ExpectedDocument, found.id, "anna") is found
    assert entry_of(lookup, ExpectedDocument, found.id) is found
    with pytest.raises(HTTPException) as caught:
        entry_of(lookup, ExpectedDocument, found.id, "ben")
    assert caught.value.status_code == 404


def test_entry_of_is_404_for_an_entry_of_another_kind() -> None:
    class Other(Entry):
        pass

    found = issuer()
    lookup = Lookup(found)
    lookup.entries[EntryAddress(kind="Other", id=found.id)] = found  # falsche Art unter der Adresse
    with pytest.raises(HTTPException) as caught:
        entry_of(lookup, Other, found.id)
    assert caught.value.status_code == 404


def test_rejection_reasons_and_text() -> None:
    result = Rejected(
        dict(
            [
                (EntryAddress(kind="Issuer", id="AAAAAAAAAA"), "Inzwischen geändert."),
                (EntryAddress(kind="Issuer", id="BBBBBBBBBB"), "Name gibt es schon."),
            ]
        )
    )
    assert rejection_reasons(result) == ["Inzwischen geändert.", "Name gibt es schon."]
    assert rejection_text(result) == "Inzwischen geändert. Name gibt es schon."


class Form(BaseModel):
    year: int = Field(ge=2000)
    note: str = Field(max_length=3)
    other: int = 0


HINTS = {"year": "Jahr: ab 2000", "note": "Notiz: höchstens 3 Zeichen"}


def test_validated_returns_the_model_without_hints() -> None:
    model, hints = validated(Form, {"year": "2024", "note": "abc"}, HINTS)
    assert model == Form(year=2024, note="abc")
    assert hints == []


def test_validated_gives_one_hint_per_field_in_error_order() -> None:
    model, hints = validated(Form, {"year": "1", "note": "abcd", "other": "x"}, HINTS)
    assert model is None
    assert hints == ["Jahr: ab 2000", "Notiz: höchstens 3 Zeichen", "other"]  # ohne Hinweis: Name


def test_validated_unknown_fields_get_the_fallback_and_an_empty_one_is_dropped() -> None:
    data = {"year": "2024", "note": "abc", "other": "x"}
    assert validated(Form, data, HINTS, "Eingabe prüfen")[1] == ["Eingabe prüfen"]
    assert validated(Form, data, HINTS, "")[1] == []


def test_validated_uses_the_innermost_field_name() -> None:
    class Outer(BaseModel):
        inner: Form

    model, hints = validated(Outer, {"inner": {"year": 1, "note": "a"}}, HINTS)
    assert model is None
    assert hints == ["Jahr: ab 2000"]
