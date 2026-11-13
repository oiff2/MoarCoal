"""Aussteller: Eintragsart, Feld am Dokument, Löschen, Befund, Sperrliste (nur tmp_path)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from moarcoal.issuers import DOCUMENT_WITHOUT_ISSUER
from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Delete,
    Document,
    EntryAddress,
    Issuer,
    Put,
    Rejected,
    Store,
    denylist_lines,
    entry_checksum,
    open_store,
)
from moarcoal.values.testing import evaluate

SHA = "a" * 64


def issuer(name: str = "Beispielbank AG", **fields: object) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, **fields)  # pyright: ignore[reportArgumentType]


def document(owner: str = "anna", sha: str = SHA, at: Issuer | None = None) -> Document:
    return Document(
        owner=owner,
        site="Ablage",
        path=f"{sha[:4]}.pdf",
        sha256=sha,
        issuer=None if at is None else at.address,
    )


def open_empty(root: Path) -> Store:
    return open_store(root, [])


def test_issuer_is_created_changed_and_deleted_through_apply(tmp_path: Path) -> None:
    store = open_empty(tmp_path)
    bank = issuer()
    assert isinstance(store.apply([Put(bank)]), Applied)
    assert (tmp_path / "common" / "issuers.json").exists()

    renamed = bank.model_copy(update={"aliases": ("Beispielbank",)})
    assert isinstance(store.apply([Put(renamed, entry_checksum(bank))]), Applied)
    assert store.state().get(bank.address) == renamed

    assert isinstance(store.apply([Delete(bank.address, entry_checksum(renamed))]), Applied)
    assert store.state().get(bank.address) is None
    assert not (tmp_path / "common" / "issuers.json").exists()


def test_issuer_survives_reopening(tmp_path: Path) -> None:
    bank = issuer(aliases=("Beispielbank",), private_person=True)
    open_empty(tmp_path).apply([Put(bank)])

    assert open_empty(tmp_path).state().get(bank.address) == bank


def test_issuer_belongs_to_everybody_and_needs_a_name() -> None:
    with pytest.raises(ValidationError):
        Issuer(owner="anna", name="Beispielbank AG")
    with pytest.raises(ValidationError):
        issuer(" ")
    with pytest.raises(ValidationError):
        issuer(aliases=("",))


def test_display_name_and_url() -> None:
    bank = issuer()
    assert bank.display_name == "Beispielbank AG"
    assert bank.url == f"/aussteller/{bank.id}"


def test_document_with_issuer_and_delete_only_without_references(tmp_path: Path) -> None:
    store = open_empty(tmp_path)
    bank = issuer()
    doc = document(at=bank)
    assert isinstance(store.apply([Put(bank), Put(doc)]), Applied)

    rejected = store.apply([Delete(bank.address, entry_checksum(bank))])
    assert isinstance(rejected, Rejected)
    assert list(rejected.reasons.values()) == ["Wird noch verwendet."]
    assert bank.address in rejected.reasons
    assert store.state().get(bank.address) == bank

    # Dokument und Aussteller zusammen zu löschen ist erlaubt
    both = [Delete(doc.address, entry_checksum(doc)), Delete(bank.address, entry_checksum(bank))]
    assert isinstance(store.apply(both), Applied)


def test_document_cannot_point_to_a_missing_issuer(tmp_path: Path) -> None:
    store = open_empty(tmp_path)

    assert isinstance(store.apply([Put(document(at=issuer()))]), Rejected)


def test_document_issuer_must_be_an_issuer() -> None:
    with pytest.raises(ValidationError):
        Document(
            owner="anna",
            site="Ablage",
            path="x.pdf",
            sha256=SHA,
            issuer=EntryAddress(kind="Document", id="ABCDEFGHIJ"),
        )


def test_old_documents_file_loads_unchanged(tmp_path: Path) -> None:
    old = document()
    fields = old.model_dump(mode="json", exclude={"issuer"})
    path = tmp_path / "users" / "anna" / "documents.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "datenebene/1", "entries": {str(old.address): fields}}))
    before = path.read_bytes()

    store = open_empty(tmp_path)

    loaded = store.state().get(old.address)
    assert isinstance(loaded, Document)
    assert loaded.issuer is None
    assert path.read_bytes() == before


def test_note_for_each_document_without_issuer_of_the_user() -> None:
    bank = issuer()
    plain = document(sha="b" * 64)
    items = [bank, document(at=bank), plain, document("berta", "c" * 64)]

    found = evaluate([], items).finding_list("anna", 2025).visible

    notes = [f for f in found if f.kind == DOCUMENT_WITHOUT_ISSUER]
    assert [n.target for n in notes] == [plain.address]
    assert notes[0].href == f"/dokumente/{plain.id}"


def test_only_private_persons_feed_the_denylist() -> None:
    landlord = issuer("Erika Mustermann", aliases=("E. Mustermann", "Frau Mustermann"))
    private = landlord.model_copy(update={"private_person": True})
    company = issuer("Beispielbank Aktiengesellschaft")

    assert denylist_lines([company, landlord]) == []
    assert denylist_lines([private, company]) == [
        "E. Mustermann",
        "Erika Mustermann",
        "Frau Mustermann",
        "Mustermann",
    ]


# --- Namen sind eindeutig ----------------------------------------------------------------------


def reasons_of(result: Applied | Rejected) -> dict[str, str]:
    assert isinstance(result, Rejected)
    return {str(address): reason for address, reason in result.reasons.items()}


def test_second_issuer_with_same_name_or_alias_is_rejected_whatever_the_spelling(
    tmp_path: Path,
) -> None:
    store = open_empty(tmp_path)
    bank = issuer(aliases=("Muster-Sparkasse",))
    assert isinstance(store.apply([Put(bank)]), Applied)
    for name in ("beispielbank ag", "  BEISPIELBANK AG ", "MUSTER-SPARKASSE"):
        twin = issuer(name)
        result = store.apply([Put(twin)])
        assert reasons_of(result) == {str(twin.address): "Name gibt es schon."}
    assert store.state().of_kind(Issuer) == [bank]


def test_alias_of_another_issuer_or_of_itself_is_rejected(tmp_path: Path) -> None:
    store = open_empty(tmp_path)
    bank, werke = issuer(), issuer("Stadtwerke Beispielstadt")
    assert isinstance(store.apply([Put(bank), Put(werke)]), Applied)
    stolen = werke.model_copy(update={"aliases": ("beispielbank ag",)})
    assert reasons_of(store.apply([Put(stolen, entry_checksum(werke))])) == {
        str(werke.address): "Name gibt es schon."
    }
    same = werke.model_copy(update={"aliases": ("Werke", " werke ")})
    assert isinstance(store.apply([Put(same, entry_checksum(werke))]), Rejected)
    as_name = werke.model_copy(update={"aliases": ("STADTWERKE beispielstadt",)})
    assert isinstance(store.apply([Put(as_name, entry_checksum(werke))]), Rejected)


def test_names_may_move_between_issuers_in_one_operation(tmp_path: Path) -> None:
    store = open_empty(tmp_path)
    bank, werke = issuer(), issuer("Stadtwerke Beispielstadt")
    assert isinstance(store.apply([Put(bank), Put(werke)]), Applied)
    moved = bank.model_copy(update={"aliases": (werke.name,)})
    result = store.apply(
        [Delete(werke.address, entry_checksum(werke)), Put(moved, entry_checksum(bank))]
    )
    assert isinstance(result, Applied)
    assert store.state().get(bank.address) == moved
