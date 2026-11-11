"""Tests der Datenebene: Einträge, Adressen und Schreibweg. Nur Wegwerfverzeichnisse."""

import json
import os
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from moarcoal.storage import (
    Applied,
    Delete,
    Entry,
    EntryAddress,
    Put,
    Rejected,
    Store,
    StoreError,
    entry_checksum,
    entry_kind,
    kind_collisions,
    new_id,
    open_store,
)


class Expense(Entry):
    year: int
    cents: int


class Trip(Entry):
    year: int


def yearly_path(entry: Expense | Trip) -> str:
    return f"users/{entry.owner}/test/{entry.year}.json"


EXPENSE_KIND = entry_kind(Expense, "test/1", yearly_path)
TRIP_KIND = entry_kind(Trip, "test/1", yearly_path)


def make_store(root: Path) -> Store:
    return open_store(root, [EXPENSE_KIND, TRIP_KIND])


def expense(cents: int = 1000, year: int = 2025, owner: str = "anna") -> Expense:
    return Expense(owner=owner, year=year, cents=cents)


def file_of(root: Path, owner: str = "anna", year: int = 2025) -> Path:
    return root / "users" / owner / "test" / f"{year}.json"


def create(store: Store, entry: Entry) -> None:
    assert isinstance(store.apply([Put(entry)]), Applied)


def temp_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.tmp"))


# --- Adressen -----------------------------------------------------------------------------


def test_new_ids_are_random_base32_of_ten_characters() -> None:
    ids = {new_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(re.fullmatch(r"[A-Z2-7]{10}", i) for i in ids)


def test_address_is_kind_plus_id_and_parses_back() -> None:
    entry = expense()
    assert str(entry.address) == f"Expense:{entry.id}"
    assert EntryAddress.parse(str(entry.address)) == entry.address
    with pytest.raises(ValueError):
        EntryAddress.parse("ohne-doppelpunkt")
    with pytest.raises(ValueError):
        EntryAddress.parse("Expense:kurz")


def test_entry_requires_an_owner() -> None:
    with pytest.raises(ValidationError):
        Expense.model_validate({"year": 2025, "cents": 1})
    with pytest.raises(ValidationError):
        Expense(owner="", year=2025, cents=1)


def test_kind_collisions_are_found() -> None:
    other_expense = type("Expense", (Entry,), {"__module__": "other"})
    assert kind_collisions([Expense, Trip]) == []
    assert kind_collisions([Expense, other_expense, Trip]) == ["Expense"]


def test_open_store_refuses_duplicate_kinds(tmp_path: Path) -> None:
    other_expense = type("Expense", (Entry,), {})
    with pytest.raises(StoreError, match="Expense"):
        open_store(
            tmp_path,
            [
                EXPENSE_KIND,
                entry_kind(other_expense, "test/1", lambda entry: f"users/{entry.owner}/x.json"),
            ],
        )


# --- Anlegen, Ändern, Löschen -----------------------------------------------------------------


def test_create_writes_stable_json_with_schema(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    result = store.apply([Put(entry)])
    assert result == Applied((Put(entry),))
    text = file_of(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("}\n")
    body = json.loads(text)
    assert body["schema"] == "test/1"
    assert list(body["entries"]) == [str(entry.address)]
    assert body["entries"][str(entry.address)]["owner"] == "anna"
    assert text == json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert store.state().get(entry.address) == entry
    assert temp_files(tmp_path) == []


def test_state_survives_reopening(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    create(store, entry)
    reopened = make_store(tmp_path)
    assert reopened.state().get(entry.address) == entry
    assert reopened.state().of_kind(Expense) == [entry]
    assert reopened.state().of_kind(Trip) == []


def test_old_state_stays_unchanged_after_apply(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    before = store.state()
    create(store, expense())
    assert len(before.entries) == 0
    assert len(store.state().entries) == 1


def test_replace_with_current_checksum(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense(cents=1000)
    create(store, entry)
    changed = entry.model_copy(update={"cents": 2500})
    result = store.apply([Put(changed, expected=entry_checksum(entry))])
    assert isinstance(result, Applied)
    assert store.state().get(entry.address) == changed
    assert make_store(tmp_path).state().get(entry.address) == changed


def test_stale_tab_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense(cents=1000)
    create(store, entry)
    stale = entry_checksum(entry)
    store.apply([Put(entry.model_copy(update={"cents": 1}), expected=stale)])
    result = store.apply([Put(entry.model_copy(update={"cents": 2}), expected=stale)])
    assert isinstance(result, Rejected)
    assert "Inzwischen geändert" in result.reasons[entry.address]
    assert store.state().get(entry.address) == entry.model_copy(update={"cents": 1})
    result = store.apply([Delete(entry.address, expected=stale)])
    assert isinstance(result, Rejected)


def test_create_refuses_existing_address_and_replace_refuses_missing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    create(store, entry)
    assert isinstance(store.apply([Put(entry)]), Rejected)
    ghost = expense()
    assert isinstance(store.apply([Put(ghost, expected="abc")]), Rejected)
    assert isinstance(store.apply([Delete(ghost.address, expected="abc")]), Rejected)


def test_delete_removes_entry_and_empty_file(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first, second = expense(), expense(cents=5)
    create(store, first)
    create(store, second)
    result = store.apply([Delete(first.address, expected=entry_checksum(first))])
    assert isinstance(result, Applied)
    assert store.state().get(first.address) is None
    assert list(json.loads(file_of(tmp_path).read_text())["entries"]) == [str(second.address)]
    store.apply([Delete(second.address, expected=entry_checksum(second))])
    assert not file_of(tmp_path).exists()
    assert len(make_store(tmp_path).state().entries) == 0


def test_moving_an_entry_to_another_file_updates_both(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense(year=2024)
    create(store, entry)
    moved = entry.model_copy(update={"year": 2025})
    assert isinstance(store.apply([Put(moved, expected=entry_checksum(entry))]), Applied)
    assert not file_of(tmp_path, year=2024).exists()
    assert make_store(tmp_path).state().get(entry.address) == moved


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_one_operation_changes_several_files_or_none(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    good = expense(year=2024)
    bad = Expense.model_construct(id=new_id(), owner="anna", year=2025, cents="viel")  # pyright: ignore[reportArgumentType]
    result = store.apply([Put(good), Put(bad)])
    assert isinstance(result, Rejected)
    assert list(result.reasons) == [bad.address]
    assert "cents" in result.reasons[bad.address]
    assert not file_of(tmp_path, year=2024).exists()
    assert len(store.state().entries) == 0
    assert isinstance(store.apply([Put(good), Put(expense(year=2025))]), Applied)
    assert file_of(tmp_path, year=2024).exists() and file_of(tmp_path, year=2025).exists()


def test_same_address_twice_in_one_operation_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    assert isinstance(store.apply([Put(entry), Put(entry)]), Rejected)
    assert len(store.state().entries) == 0


def test_unregistered_kind_and_unsafe_path_are_rejected(tmp_path: Path) -> None:
    class Stranger(Entry):
        pass

    store = make_store(tmp_path)
    assert isinstance(store.apply([Put(Stranger(owner="anna"))]), Rejected)
    assert isinstance(store.apply([Put(expense(owner="../../etc"))]), Rejected)
    assert isinstance(store.apply([Put(expense(owner="/abs"))]), Rejected)
    assert list(tmp_path.iterdir()) == []


# --- Handänderung ---------------------------------------------------------------------------


def test_hand_edited_file_is_rejected_not_overwritten(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    create(store, entry)
    path = file_of(tmp_path)
    edited = path.read_text().replace('"cents": 1000', '"cents": 9999')
    path.write_text(edited)
    result = store.apply([Put(expense(cents=5))])
    assert isinstance(result, Rejected)
    assert "von Hand" in next(iter(result.reasons.values()))
    assert path.read_text() == edited
    changed = entry.model_copy(update={"cents": 1})
    result = store.apply([Put(changed, expected=entry_checksum(entry))])
    assert isinstance(result, Rejected)


def test_hand_created_file_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    path = file_of(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    assert isinstance(store.apply([Put(expense())]), Rejected)
    assert path.read_text() == "{}"


def test_untouched_hand_edited_file_does_not_block_other_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    create(store, expense(year=2024))
    file_of(tmp_path, year=2024).write_text("{}")
    assert isinstance(store.apply([Put(expense(year=2025))]), Applied)


# --- Abbruch mitten im Schreiben --------------------------------------------------------------


def test_failure_while_renaming_leaves_everything_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    old = expense(year=2024, cents=1)
    create(store, old)
    before = file_of(tmp_path, year=2024).read_bytes()
    real_replace = os.replace
    calls: list[int] = []

    def flaky(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise OSError("Platte voll")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    changes = [
        Put(old.model_copy(update={"cents": 2}), expected=entry_checksum(old)),
        Put(expense(year=2025)),
    ]
    with pytest.raises(OSError, match="Platte voll"):
        store.apply(changes)
    monkeypatch.undo()
    assert file_of(tmp_path, year=2024).read_bytes() == before
    assert not file_of(tmp_path, year=2025).exists()
    assert temp_files(tmp_path) == []
    assert store.state().get(old.address) == old
    assert len(store.state().entries) == 1
    assert isinstance(store.apply(changes), Applied)  # auch die Prüfsummen sind wieder stimmig


def test_leftover_temp_file_from_a_crash_is_discarded_on_open(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    create(store, entry)
    leftover = file_of(tmp_path).with_name("2025.json.tmp")
    leftover.write_text("halb gesch")
    reopened = make_store(tmp_path)
    assert not leftover.exists()
    assert reopened.state().get(entry.address) == entry


def test_open_names_the_broken_file(tmp_path: Path) -> None:
    path = file_of(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("kein json")
    with pytest.raises(StoreError, match=r"2025\.json"):
        make_store(tmp_path)


def test_open_refuses_entry_in_the_wrong_file(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense(year=2025)
    create(store, entry)
    file_of(tmp_path).rename(file_of(tmp_path, year=2030))
    with pytest.raises(StoreError, match="gehört nicht in diese Datei"):
        make_store(tmp_path)


def test_open_refuses_wrong_schema(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    create(store, expense())
    path = file_of(tmp_path)
    path.write_text(path.read_text().replace("test/1", "test/2"))
    with pytest.raises(StoreError, match="Format"):
        make_store(tmp_path)


# --- Sicherungen -------------------------------------------------------------------------------


def test_backup_keeps_previous_versions_and_only_the_last_twenty(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense(cents=0)
    create(store, entry)
    backups = tmp_path / ".backup" / "users" / "anna" / "test" / "2025.json"
    assert not backups.exists()  # beim Anlegen gab es nichts zu sichern
    current = entry
    for cents in range(1, 26):
        newer = current.model_copy(update={"cents": cents})
        store.apply([Put(newer, expected=entry_checksum(current))])
        current = newer
    files = sorted(backups.glob("*.json"))
    assert len(files) == 20
    newest = json.loads(files[-1].read_text())
    assert newest["entries"][str(entry.address)]["cents"] == 24
    assert make_store(tmp_path).state().get(entry.address) == current


def test_backup_is_not_loaded_as_data(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = expense()
    create(store, entry)
    store.apply([Put(entry.model_copy(update={"cents": 7}), expected=entry_checksum(entry))])
    assert len(make_store(tmp_path).state().entries) == 1
