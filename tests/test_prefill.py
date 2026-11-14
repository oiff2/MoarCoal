"""Tests: Vorbelegen des Aufnehmen-Formulars aus dem Datei- und Ordnernamen (nur tmp_path)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.documents import DocumentKind
from moarcoal.prefill import Prefill, prefill_from_name
from moarcoal.storage import COMMON_OWNER, Issuer, Put, State, Store

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
PORT = 4711


def kind(key: str, *patterns: str) -> DocumentKind:
    return DocumentKind(key, key, True, lambda document, content: [], name_patterns=patterns)


def issuer(name: str, *aliases: str) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, aliases=aliases)


def state_with(*issuers: Issuer) -> State:
    return State({i.address: i for i in issuers})


# --- Aussteller --------------------------------------------------------------------------------


def test_issuer_from_name_or_alias_in_file_or_folder_name() -> None:
    bank = issuer("Beispielbank AG", "Sparkasse Muster")
    state = state_with(bank, issuer("Stadtwerke Beispielstadt"))
    assert prefill_from_name(state, [], "Konto/beispielbank_ag_2025.pdf").issuer == bank
    assert prefill_from_name(state, [], "Sparkasse-Muster/auszug.pdf").issuer == bank
    assert prefill_from_name(state, [], "Gibtsnicht/auszug.pdf").issuer is None


def test_ambiguous_issuer_prefills_nothing() -> None:
    state = state_with(issuer("Beispielbank"), issuer("Musterversicherung"))
    assert prefill_from_name(state, [], "Beispielbank/Musterversicherung.pdf").issuer is None


def test_issuer_matches_whole_words_only_and_not_tiny_names() -> None:
    state = state_with(issuer("Bank"), issuer("AG"))
    assert prefill_from_name(state, [], "Bankgebuehren.pdf").issuer is None
    assert prefill_from_name(state, [], "AG.pdf").issuer is None


# --- Jahr --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "Steuer/2025/x.pdf",
        "x_2025-03-14.pdf",
        "x 14.03.2025.pdf",
        "x_20250314.pdf",
        "2025/x_2025.pdf",
    ],
)
def test_year_from_number_or_date(path: str) -> None:
    assert prefill_from_name(State({}), [], path).year == 2025


@pytest.mark.parametrize(
    "path", ["x.pdf", "2024/x_2025.pdf", "x_2025-01-05_2026-01-05.pdf", "x_12025.pdf", "x_1999.pdf"]
)
def test_missing_or_ambiguous_year_prefills_nothing(path: str) -> None:
    assert prefill_from_name(State({}), [], path).year is None


# --- Dokumentart -------------------------------------------------------------------------------


def test_kind_from_pattern_only() -> None:
    kinds = [kind("protocol", "protokoll"), kind("bill", r"\brechnung\b"), kind("none")]
    assert (
        prefill_from_name(State({}), kinds, "Uebertragungsprotokoll_2025.html").kind == "protocol"
    )
    assert prefill_from_name(State({}), kinds, "Meine-Rechnung.pdf").kind == "bill"
    assert prefill_from_name(State({}), kinds, "scan0001.pdf") == Prefill()
    assert prefill_from_name(State({}), [kind("none")], "protokoll.pdf").kind is None


def test_two_matching_kinds_prefill_nothing() -> None:
    kinds = [kind("protocol", "protokoll"), kind("bill", "rechnung")]
    assert prefill_from_name(State({}), kinds, "Rechnung_Protokoll.pdf").kind is None


# --- Formular ----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    site = tmp_path / "ablage"
    (site / "Beispielbank AG").mkdir(parents=True)
    (site / "Beispielbank AG" / "Protokoll_2025.html").write_bytes(FIXTURE.read_bytes())
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def add(client: httpx.Client, *names: str) -> list[Issuer]:
    issuers = [issuer(n) for n in names]
    store_of(client).apply([Put(i) for i in issuers])
    return issuers


def form(client: httpx.Client) -> str:
    return client.get(f"/belege?datei={SHA}").text.split('<div class="formular">')[1]


def test_form_is_prefilled_and_marked_from_name(client: httpx.Client) -> None:
    (bank,) = add(client, "Beispielbank AG")
    html = form(client)
    assert f'"default": "{bank.id}"' in html
    assert html.count("aus Name") == 2  # Aussteller und Jahr; echte Arten tragen kein Muster
    assert '<option value="transfer_protocol" selected>' not in html
    assert 'name="year" value="2025"' in html


def test_page_writes_nothing_and_never_takes_in(client: httpx.Client) -> None:
    add(client, "Beispielbank AG")
    before = store_of(client).state()
    form(client)
    assert store_of(client).state() == before


def test_name_match_beats_last_issuer_preset_only_when_unambiguous(client: httpx.Client) -> None:
    (bank,) = add(client, "Beispielbank AG")
    assert f'"default": "{bank.id}"' in form(client)
    add(client, "Protokoll")  # zweiter Treffer im Pfad: mehrdeutig, kein Name-Vorschlag
    html = form(client)
    assert '"default": ""' in html
    assert html.count("aus Name") == 1
