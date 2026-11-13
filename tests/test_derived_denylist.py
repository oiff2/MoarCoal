"""Abgeleitete Sperrliste: Store schreibt sie, privacy_guard liest sie (nur tmp_path)."""

import logging
from pathlib import Path

import privacy_guard as pg
import pytest

from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Delete,
    Issuer,
    Merge,
    Put,
    entry_checksum,
    open_store,
)

DENYLIST = "common/derived-denylist.txt"


def person(name: str, **fields: object) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, private_person=True, **fields)  # pyright: ignore[reportArgumentType]


def lines(root: Path) -> list[str]:
    return (root / DENYLIST).read_text(encoding="utf-8").splitlines()


def test_private_person_is_listed_and_company_is_not(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    company = Issuer(owner=COMMON_OWNER, name="Beispielbank Aktiengesellschaft")
    assert isinstance(store.apply([Put(person("Erika Mustermann")), Put(company)]), Applied)
    assert lines(tmp_path) == ["Erika Mustermann", "Mustermann"]


def test_change_delete_and_merge_keep_the_file_current(tmp_path: Path) -> None:
    store = open_store(tmp_path, [])
    anna, berta = person("Erika Mustermann"), person("Berta Musterfrau")
    store.apply([Put(anna), Put(berta)])

    renamed = anna.model_copy(update={"name": "Erika Musterlehrer"})
    store.apply([Put(renamed, entry_checksum(anna))])
    assert "Mustermann" not in lines(tmp_path)
    assert "Musterlehrer" in lines(tmp_path)

    store.apply([Delete(berta.address, entry_checksum(berta))])
    assert lines(tmp_path) == ["Erika Musterlehrer", "Musterlehrer"]

    other = person("Hans Musterhaus")
    store.apply([Put(other)])
    state = store.state()
    merge = Merge(
        other.address,
        renamed.address,
        state.checksum(other.address) or "",
        state.checksum(renamed.address) or "",
    )
    assert isinstance(store.apply([merge]), Applied)
    assert "Musterhaus" in lines(tmp_path)  # Name der Quelle wird Alias des Ziels


def test_file_is_written_on_open(tmp_path: Path) -> None:
    open_store(tmp_path, []).apply([Put(person("Erika Mustermann"))])
    (tmp_path / DENYLIST).unlink()
    open_store(tmp_path, [])
    assert lines(tmp_path) == ["Erika Mustermann", "Mustermann"]


def test_failed_write_does_not_fail_the_operation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = open_store(tmp_path, [])
    (tmp_path / DENYLIST).mkdir(parents=True)  # Datei lässt sich nicht lesen oder ersetzen
    with caplog.at_level(logging.WARNING):
        assert isinstance(store.apply([Put(person("Erika Mustermann"))]), Applied)
    assert "Sperrliste" in caplog.text
    assert "Mustermann" not in caplog.text


# --- privacy_guard liest die Datei ---------------------------------------------------------------


@pytest.fixture
def guard_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MOARCOAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(pg, "DENYLIST_PATH", tmp_path / "keine-handliste.txt")
    return tmp_path / "data"


def test_guard_blocks_a_derived_value(guard_dirs: Path, tmp_path: Path) -> None:
    open_store(guard_dirs, []).apply([Put(person("Erika Mustermann"))])
    message = tmp_path / "msg.txt"
    message.write_text("fix: Rechnung von Erika Mustermann\n", encoding="utf-8")
    assert pg.main(["x", "file", str(message)]) == 1
    message.write_text("fix: Rechnung\n", encoding="utf-8")
    assert pg.main(["x", "file", str(message)]) == 0


def test_guard_without_data_dir_or_file_is_unchanged(guard_dirs: Path, tmp_path: Path) -> None:
    message = tmp_path / "msg.txt"
    message.write_text("fix: Rechnung von Erika Mustermann\n", encoding="utf-8")
    assert not guard_dirs.exists()
    assert pg.main(["x", "file", str(message)]) == 0
    (guard_dirs / "common").mkdir(parents=True)
    assert pg.main(["x", "file", str(message)]) == 0
