"""Tests: tools/kohlebau_import.py mit einem erfundenen Kohlebau-Ordner (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import kohlebau_import as ki
import pytest

from moarcoal.modules import MODULES
from moarcoal.registration import open_module_store
from moarcoal.storage import COMMON_OWNER, Document, Issuer, PersonalDetails, Put, State

FIXTURES = Path(__file__).parent / "fixtures"
PROTOCOL = (FIXTURES / "uebertragungsprotokoll_2025.html").read_bytes()
WAGE_TAX = (FIXTURES / "lohnsteuerbescheinigung_2025.html").read_bytes()
LETTER = b"ein erfundener Brief"
OUTSIDE = b"liegt in keinem Ablageort"


def beleg(
    id: str, content: bytes, *, art: str = "beleg", typ: str = "", issuer: str = ""
) -> dict[str, str]:
    return {
        "id": id,
        "art": art,
        "belegtyp": typ,
        "aussteller": issuer,
        "pfad": f"{id}.bin",
        "pruefsumme": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path]:
    """(Kohlebau-Ordner, Datenverzeichnis) mit Ablageort und erfundenen Daten."""
    site = tmp_path / "ablage" / "2025"
    site.mkdir(parents=True)
    (site / "protokoll.html").write_bytes(PROTOCOL)
    (site / "lohn.html").write_bytes(WAGE_TAX)
    (site / "brief.txt").write_bytes(LETTER)
    data = tmp_path / "daten"
    (data / "common").mkdir(parents=True)
    (data / "common" / "sites.json").write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(tmp_path / "ablage")}}),
        encoding="utf-8",
    )
    root = tmp_path / "kohlebau"
    (root / "2025" / ".kohlebau").mkdir(parents=True)
    (root / "aussteller.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "aussteller": [
                    {"id": "selbst", "name": "selbst"},
                    {"id": "bank", "name": "Beispielbank AG", "aliasse": ["Beispielbank"]},
                    {"id": "amt", "name": "Finanzamt Beispielstadt", "fruehere_ids": ["amt-alt"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "2025" / ".kohlebau" / "steuerjahr.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "steuerjahr": 2025,
                "belege": [
                    beleg("b1", PROTOCOL, art="uebertragungsprotokoll", issuer="amt-alt"),
                    beleg("b2", WAGE_TAX, typ="Lohnsteuerbescheinigung", issuer="bank"),
                    beleg("b3", LETTER, typ="Sonstiges", issuer="bank"),
                    beleg("b4", OUTSIDE),
                ],
                "eintraege": [{"wert": "99999"}],
            }
        ),
        encoding="utf-8",
    )
    return root, data


def state_of(data: Path) -> State:
    return open_module_store(data, MODULES).state()


def documents(data: Path) -> dict[str, Document]:
    return {d.path: d for d in state_of(data).of_kind(Document)}


def test_issuers_and_documents_are_taken_over(setup: tuple[Path, Path]) -> None:
    root, data = setup
    report = ki.run(root, data, 2025, "ich")
    issuers = {i.name: i for i in state_of(data).of_kind(Issuer)}
    assert set(issuers) == {"Beispielbank AG", "Finanzamt Beispielstadt"}
    assert issuers["Beispielbank AG"].aliases == ("Beispielbank",)
    docs = documents(data)
    protocol = docs["2025/protokoll.html"]
    assert protocol.document_kind == "transfer_protocol"
    assert protocol.period_start is not None and protocol.period_start.year == 2025
    assert protocol.issuer == issuers["Finanzamt Beispielstadt"].address  # frühere Kennung
    assert docs["2025/lohn.html"].document_kind == "wage_tax_certificate"
    assert docs["2025/lohn.html"].issuer == issuers["Beispielbank AG"].address
    assert docs["2025/brief.txt"].document_kind is None
    assert docs["2025/brief.txt"].issuer == issuers["Beispielbank AG"].address
    assert report.counts["Aussteller angelegt"] == 2
    assert report.counts["Beleg aufgenommen (mit Art)"] == 2
    assert report.counts["Beleg aufgenommen (ohne Art)"] == 1


def test_file_outside_every_site_is_reported_not_aborted(setup: tuple[Path, Path]) -> None:
    root, data = setup
    report = ki.run(root, data, 2025, "ich")
    assert report.counts["Beleg nicht in einem Ablageort"] == 1
    assert any("b4" in line for line in report.lines())
    assert len(documents(data)) == 3


def test_second_run_changes_nothing(setup: tuple[Path, Path]) -> None:
    root, data = setup
    ki.run(root, data, 2025, "ich")
    before = state_of(data).entries
    report = ki.run(root, data, 2025, "ich")
    assert state_of(data).entries == before
    assert report.counts["Aussteller vorhanden"] == 2
    assert report.counts["Beleg schon aufgenommen"] == 3
    assert "Aussteller angelegt" not in report.counts


def test_existing_issuer_is_found_by_name_or_alias(setup: tuple[Path, Path]) -> None:
    root, data = setup
    known = Issuer(
        owner=COMMON_OWNER, name="Beispielbank Aktiengesellschaft", aliases=("beispielbank",)
    )
    open_module_store(data, MODULES).apply([Put(known)])
    report = ki.run(root, data, 2025, "ich")
    names = {i.name for i in state_of(data).of_kind(Issuer)}
    assert names == {"Beispielbank Aktiengesellschaft", "Finanzamt Beispielstadt"}
    assert report.counts["Aussteller vorhanden"] == 1
    assert documents(data)["2025/lohn.html"].issuer == known.address


def test_ambiguous_issuer_is_reported_and_skipped(setup: tuple[Path, Path]) -> None:
    root, data = setup
    open_module_store(data, MODULES).apply(
        [
            Put(Issuer(owner=COMMON_OWNER, name="Beispielbank AG")),
            Put(Issuer(owner=COMMON_OWNER, name="Andere Bank", aliases=("Beispielbank",))),
        ]
    )
    report = ki.run(root, data, 2025, "ich")
    assert report.counts["Aussteller mehrdeutig"] == 1
    assert {i.name for i in state_of(data).of_kind(Issuer)} == {
        "Beispielbank AG",
        "Andere Bank",
        "Finanzamt Beispielstadt",
    }
    assert documents(data)["2025/lohn.html"].issuer is None


def test_own_issuer_comes_from_the_personal_details(setup: tuple[Path, Path]) -> None:
    root, data = setup
    steuerjahr = root / "2025" / ".kohlebau" / "steuerjahr.json"
    content = json.loads(steuerjahr.read_text(encoding="utf-8"))
    content["belege"][2]["aussteller"] = "selbst"
    steuerjahr.write_text(json.dumps(content), encoding="utf-8")
    store = open_module_store(data, MODULES)
    own = Issuer(owner=COMMON_OWNER, name="Max Mustermann", private_person=True)
    details = PersonalDetails(
        owner="ich", first_name="Max", last_name="Mustermann", issuer=own.address
    )
    store.apply([Put(own), Put(details)])
    ki.run(root, data, 2025, "ich")
    assert documents(data)["2025/brief.txt"].issuer == own.address


def test_field_values_are_not_taken_over(setup: tuple[Path, Path]) -> None:
    root, data = setup
    ki.run(root, data, 2025, "ich")
    assert "99999" not in "".join(p.read_text() for p in data.rglob("*.json") if p.is_file())


def test_unreadable_source_stops_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = ki.main([str(tmp_path), "--data-dir", str(tmp_path / "daten")])
    assert code == 1
    assert "Abbruch" in capsys.readouterr().err
