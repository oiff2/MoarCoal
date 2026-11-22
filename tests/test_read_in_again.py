"""Tests: neu einlesen beim Start und der Befund „Einlesen hat einen Wert geändert“ (tmp_path)."""

import datetime
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal import documents
from moarcoal.documents import (
    DocumentKind,
    ReadInError,
    ReadInRuleBroken,
    TakenIn,
    read_in_again,
    take_in,
)
from moarcoal.modules.tax_year import REGISTRATION, TRANSFER_PROTOCOL, ProtocolReading
from moarcoal.modules.tax_year.reading import READER_VERSION
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    ReadInEntry,
    Rereading,
    Store,
    entry_checksum,
    open_store,
)
from moarcoal.values.engine import Values
from moarcoal.values.findings import READ_IN_CHANGED, Finding, Severity
from moarcoal.web.helpers import linked_findings

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PATH = "2025/protokoll.html"
PORT = 4711
NOW = datetime.datetime(2026, 4, 1, 8, 0, tzinfo=datetime.UTC)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    shutil.copy(FIXTURE, folder / PATH)
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "daten"


def make_store(root: Path, site: Path) -> Store:
    return open_store(root, REGISTRATION.kinds, {"Belege": site})


def version(number: int, change: dict[int, str] | None = None) -> DocumentKind:
    """Die echte Regel als Fassung `number`; `change` ersetzt den Inhalt von Zeilen (ab 0)."""

    def read_in(document: Document, content: bytes) -> list[ReadInEntry]:
        (reading,) = TRANSFER_PROTOCOL.read_in(document, content)
        assert isinstance(reading, ProtocolReading)
        lines = tuple(
            line.model_copy(update={"content": (change or {}).get(i, line.content)})
            for i, line in enumerate(reading.lines)
        )
        return [reading.model_copy(update={"reader_version": number, "lines": lines})]

    return replace(TRANSFER_PROTOCOL, read_in=read_in, reader_version=number, after_take_in=None)


def client(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def taken_in(root: Path, site: Path, kind: DocumentKind) -> ProtocolReading:
    store = make_store(root, site)
    result = take_in(store, {kind.key: kind}, "anna", "Belege", PATH, kind.key, 2025)
    assert isinstance(result, TakenIn)
    (reading,) = result.entries
    assert isinstance(reading, ProtocolReading)
    return reading


def reread(root: Path, site: Path, kind: DocumentKind) -> tuple[Store, list[str]]:
    store = make_store(root, site)
    return store, read_in_again(store, {kind.key: kind}, NOW)


# --- neu einlesen -----------------------------------------------------------------------------


def test_changed_value_replaces_the_old_one_under_the_same_address(root: Path, site: Path) -> None:
    before = taken_in(root, site, version(1))
    store, report = reread(root, site, version(2, {0: "221"}))
    (after,) = store.state().of_kind(ProtocolReading)
    assert after.address == before.address
    assert (after.reader_version, after.lines[0].content) == (2, "221")
    (rereading,) = store.state().of_kind(Rereading)
    assert (rereading.document, rereading.reread_at) == (before.document, NOW)
    assert (rereading.version_before, rereading.version_after) == (1, 2)
    assert rereading.difference_count == 1
    (difference,) = rereading.differences
    assert (difference.location, difference.before, difference.after) == (
        "ProtocolReading.lines[1].content",
        "220",
        "221",
    )
    assert report == [f"Belege/{PATH}: neu eingelesen, 1 Stelle(n) geändert."]
    assert make_store(root, site).state().entries == store.state().entries  # gespeichert


def test_same_result_only_updates_the_version_without_rereading(root: Path, site: Path) -> None:
    taken_in(root, site, version(1))
    store, _ = reread(root, site, version(2))
    (reading,) = store.state().of_kind(ProtocolReading)
    assert reading.reader_version == 2
    assert store.state().of_kind(Rereading) == []


def test_rereading_falls_with_its_document(root: Path, site: Path) -> None:
    before = taken_in(root, site, version(1))
    store, _ = reread(root, site, version(2, {0: "221"}))
    document = store.state().entries[before.document]
    result = store.apply([Delete(document.address, entry_checksum(document))])
    assert isinstance(result, Applied)
    assert store.state().of_kind(Rereading) == []
    assert store.state().of_kind(ProtocolReading) == []


def test_current_version_is_not_read_again(root: Path, site: Path) -> None:
    taken_in(root, site, version(2))
    (site / PATH).unlink()  # würde beim Lesen auffallen
    store, report = reread(root, site, version(2, {0: "999"}))
    assert report == []
    assert store.state().of_kind(Rereading) == []


def remove(file: Path) -> None:
    file.unlink()


def overwrite(file: Path) -> None:
    file.write_text("anders", encoding="utf-8")


@pytest.mark.parametrize(
    ("damage", "reason"), [(remove, "keine Datei"), (overwrite, "Inhalt der Datei")]
)
def test_missing_or_changed_file_keeps_the_old_result(
    root: Path, site: Path, damage: Callable[[Path], object], reason: str
) -> None:
    before = taken_in(root, site, version(1))
    damage(site / PATH)
    store, report = reread(root, site, version(2, {0: "221"}))
    assert store.state().of_kind(ProtocolReading) == [before]
    assert store.state().of_kind(Rereading) == []
    assert len(report) == 1 and reason in report[0]


def test_rule_that_now_refuses_keeps_the_old_result(root: Path, site: Path) -> None:
    before = taken_in(root, site, version(1))

    def refusing(document: Document, content: bytes) -> list[ReadInEntry]:
        raise ReadInError("Neue Regel lehnt ab.")

    store, report = reread(root, site, replace(version(2), read_in=refusing))
    assert store.state().of_kind(ProtocolReading) == [before]
    assert report == [f"Belege/{PATH}: nicht neu eingelesen, Neue Regel lehnt ab."]


def test_several_entries_of_a_kind_are_replaced_as_a_whole(root: Path, site: Path) -> None:
    def split(number: int, content: str) -> DocumentKind:
        def read_in(document: Document, data: bytes) -> list[ReadInEntry]:
            (reading,) = version(number).read_in(document, data)
            assert isinstance(reading, ProtocolReading)
            first = reading.lines[0].model_copy(update={"content": content})
            return [
                reading.model_copy(update={"lines": (first,)}),
                ProtocolReading.model_validate(reading.model_dump(exclude={"id"})),
            ]

        return replace(
            TRANSFER_PROTOCOL, read_in=read_in, reader_version=number, after_take_in=None
        )

    first = split(1, "220")
    result = take_in(
        make_store(root, site), {first.key: first}, "anna", "Belege", PATH, first.key, 2025
    )
    assert isinstance(result, TakenIn)
    store, _ = reread(root, site, split(2, "221"))
    assert len(store.state().of_kind(ProtocolReading)) == 2
    (rereading,) = store.state().of_kind(Rereading)
    assert rereading.difference_count == 2
    assert [(d.before is None, d.after is None) for d in rereading.differences] == [
        (False, True),
        (True, False),
    ]


def test_many_differences_are_counted_but_only_the_first_kept(
    root: Path, site: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(documents, "MAX_DIFFERENCES", 2)
    taken_in(root, site, version(1))
    store, _ = reread(root, site, version(2, {i: f"{i}9" for i in range(5)}))
    (rereading,) = store.state().of_kind(Rereading)
    assert (rereading.difference_count, len(rereading.differences)) == (5, 2)


def test_rule_must_name_document_owner_and_version(root: Path, site: Path) -> None:
    store = make_store(root, site)
    wrong = replace(version(1), reader_version=2)  # Regel stempelt 1, Art sagt 2
    with pytest.raises(ReadInRuleBroken):
        take_in(store, {wrong.key: wrong}, "anna", "Belege", PATH, wrong.key, 2025)
    assert store.state().entries == {}


# --- Befund -----------------------------------------------------------------------------------


def notes(
    modules: tuple[ModuleRegistration, ...], store: Store, user: str, year: int
) -> list[Finding]:
    """Die Befunde „Einlesen hat einen Wert geändert“ des Nutzers im Jahr."""
    state = store.state()
    found = Values(modules, state, sites=store.sites).finding_list(user, year)
    return [f for f in linked_findings(modules, state, found).visible if f.kind == READ_IN_CHANGED]


def test_rereading_gives_a_note_with_the_changes_and_a_link(root: Path, site: Path) -> None:
    before = taken_in(root, site, version(1))
    store, _ = reread(root, site, version(2, {0: "221", 1: "13", 2: "50,00", 3: "21,00"}))
    # ohne Werte und Abgleich des Steuerjahrs, die Werte von Arbeit bräuchten
    modules = (replace(REGISTRATION, document_kinds=(version(2),), findings=None, values=()),)
    (finding,) = notes(modules, store, "anna", 2025)
    (rereading,) = store.state().of_kind(Rereading)
    assert (finding.severity, finding.target) == (Severity.NOTE, rereading.address)
    assert finding.message.startswith(
        f"Übertragungsprotokoll {PATH}: Neues Einlesen (Fassung 1 → 2) hat 4 Stelle(n) geändert: "
        "ProtocolReading.lines[1].content „220“ → „221“; "
    )
    assert finding.message.endswith(" und 1 weitere.")
    assert finding.href == f"/steuerjahr/uebertragungsprotokolle/{before.id}"
    assert notes(modules, store, "anna", 2024) == []
    assert notes(modules, store, "ben", 2025) == []


def test_app_start_reads_in_again_and_lists_the_note(root: Path, site: Path) -> None:
    taken_in(root, site, version(1, {0: "999"}))
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True, exist_ok=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(PORT, root, user="anna")
    store: Store = app.state.store
    (reading,) = store.state().of_kind(ProtocolReading)
    assert (reading.reader_version, reading.lines[0].content) == (READER_VERSION, "220")
    page = client(app).get("/befunde?year=2025").text
    assert "Neues Einlesen (Fassung 1 → 2) hat 1 Stelle(n) geändert" in page
    assert "„999“ → „220“" in page
