"""Tests: Bezeichnung am Dokument und sein Anzeigename „Aussteller · Bezeichnung“ (#183)."""

import hashlib
import json
from pathlib import Path

import httpx
import kohlebau_import as ki
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient
from test_kohlebau_import import documents, setup  # noqa: F401 (Fixture)

from moarcoal.documents import (
    DocumentKind,
    TakenIn,
    change_document,
    document_name,
    read_document_choice,
    take_in,
)
from moarcoal.modules import MODULES
from moarcoal.registration import open_module_store
from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Document,
    Issuer,
    Put,
    Store,
    entry_checksum,
    open_store,
)
from moarcoal.storage.documents import TEXT_MAX

KINDS: dict[str, DocumentKind] = {}
PORT = 8798
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


@pytest.fixture
def store(tmp_path: Path) -> Store:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "zinsen_2025.pdf").write_text("Zinsen")
    return open_store(tmp_path / "daten", [], sites={"Belege": site})


def taken(store: Store, label: str | None = "Zinsbescheinigung") -> Document:
    result = take_in(store, KINDS, "anna", "Belege", "zinsen_2025.pdf", "", 2025, label=label)
    assert isinstance(result, TakenIn)
    return result.document


def test_take_in_stores_the_label(store: Store) -> None:
    assert taken(store).label == "Zinsbescheinigung"


def test_label_can_be_changed_and_removed(store: Store) -> None:
    document = taken(store)
    result = change_document(store, KINDS, document, None, label="Zinsen Tagesgeld")
    assert isinstance(result, Applied)
    (changed,) = store.state().of_kind(Document)
    assert changed.label == "Zinsen Tagesgeld"
    result = change_document(store, KINDS, changed, None, label=None)
    assert isinstance(result, Applied)
    assert next(iter(store.state().of_kind(Document))).label is None


def test_change_without_label_keeps_it(store: Store) -> None:
    document = taken(store)
    assert isinstance(change_document(store, KINDS, document, None), Applied)
    assert next(iter(store.state().of_kind(Document))).label == "Zinsbescheinigung"


def test_form_reads_label_trimmed_empty_is_none_and_too_long_is_rejected(store: Store) -> None:
    state = store.state()
    choice = read_document_choice(state, KINDS, {"label": "  Zinsen  "})
    assert not isinstance(choice, tuple) and getattr(choice, "label", None) == "Zinsen"
    empty = read_document_choice(state, KINDS, {"label": "   "})
    assert getattr(empty, "label", "x") is None
    too_long = read_document_choice(state, KINDS, {"label": "x" * (TEXT_MAX + 1)})
    assert getattr(too_long, "reasons", ())


def test_document_name_issuer_label_or_file_name(store: Store) -> None:
    bank = Issuer(owner=COMMON_OWNER, name="Beispielbank AG")
    store.apply([Put(bank)])
    document = taken(store)
    state = store.state()
    assert document_name(document, state) == "Zinsbescheinigung"
    with_issuer = document.model_copy(update={"issuer": bank.address})
    store.apply([Put(with_issuer)])
    assert document_name(with_issuer, store.state()) == "Beispielbank AG · Zinsbescheinigung"
    without_label = with_issuer.model_copy(update={"label": None})
    assert document_name(without_label, store.state()) == "zinsen_2025.pdf"


# --- Oberfläche -----------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> httpx.Client:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "brief.txt").write_text("ein Brief")
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}))
    app = make_app(PORT, tmp_path / "daten", user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def store_of(client: httpx.Client) -> Store:
    return client.app.state.store  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


def test_intake_and_document_form_carry_the_label(client: httpx.Client) -> None:
    sha = hashlib.sha256(b"ein Brief").hexdigest()
    page = client.get(f"/belege?datei={sha}").text
    assert 'name="label"' in page
    response = client.post(
        "/belege/aufnehmen",
        data={"sha256": sha, "kind": "", "label": "Brief vom Amt"},
        headers=ORIGIN,
    )
    assert response.status_code == 303
    (document,) = store_of(client).state().of_kind(Document)
    assert document.label == "Brief vom Amt"

    listing = client.get(f"/belege/dokumente?dokument={document.id}").text
    assert "Brief vom Amt" in listing
    assert 'name="label" value="Brief vom Amt"' in listing

    client.post(f"/dokumente/{document.id}/aendern", data={"label": "Bescheid"}, headers=ORIGIN)
    (changed,) = store_of(client).state().of_kind(Document)
    assert changed.label == "Bescheid"


# --- Übernahme aus Kohlebau -----------------------------------------------------------------


def test_kohlebau_import_fills_the_label_once(setup: tuple[Path, Path]) -> None:  # noqa: F811
    root, data = setup
    ki.run(root, data, 2025, "ich")
    docs = documents(data)
    assert docs["2025/lohn.html"].label == "Lohnsteuerbescheinigung"
    assert docs["2025/protokoll.html"].label is None  # ohne Belegtyp keine Bezeichnung

    store = open_module_store(data, MODULES)
    letter, wage = docs["2025/brief.txt"], docs["2025/lohn.html"]
    applied = store.apply(
        [
            Put(letter.model_copy(update={"label": "Von Hand"}), entry_checksum(letter)),
            # aufgenommen vor der Bezeichnung
            Put(wage.model_copy(update={"label": None}), entry_checksum(wage)),
        ]
    )
    assert isinstance(applied, Applied)
    report = ki.run(root, data, 2025, "ich")
    after = documents(data)
    assert after["2025/brief.txt"].label == "Von Hand"
    assert after["2025/lohn.html"].label == "Lohnsteuerbescheinigung"
    assert report.counts["Bezeichnung nachgetragen"] == 1
    assert ki.run(root, data, 2025, "ich").counts.get("Bezeichnung nachgetragen", 0) == 0
