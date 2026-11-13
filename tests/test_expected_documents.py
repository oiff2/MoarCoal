"""Erwarteter Beleg in einfacher Form: Eintragsart, Befunde, Seite, Fundstelle (nur tmp_path)."""

import datetime
import re
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DocumentKind
from moarcoal.expected_documents import DUPLICATE, PENDING, matching_documents, previous_year_issuer
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import TRANSFER_PROTOCOL
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import (
    COMMON_OWNER,
    Document,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    Merge,
    Put,
    open_store,
)
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import (
    Amount,
    Backing,
    ExpectedDocumentLocator,
    ExposedValue,
    Period,
    Unit,
    ValueKey,
)
from moarcoal.values.testing import evaluate

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
KIND = TRANSFER_PROTOCOL.key
SHA = "a" * 64


def document(
    year: int | None = 2025, kind: str = KIND, sha: str = SHA, owner: str = "anna"
) -> Document:
    start = None if year is None else datetime.date(year, 1, 1)
    end = None if year is None else datetime.date(year, 12, 31)
    return Document(
        owner=owner,
        site="Ablage",
        path=f"{sha[:4]}.html",
        sha256=sha,
        document_kind=kind,
        period_start=start,
        period_end=end,
    )


def expected(start: int = 2025, end: int | None = None, owner: str = "anna") -> ExpectedDocument:
    return ExpectedDocument(
        owner=owner, document_kind=KIND, start_year=start, end_year=end, description="Beispiel"
    )


def findings(entries: list[object], year: int = 2025, user: str = "anna"):
    values = evaluate([WORK, TAX_YEAR], entries)  # pyright: ignore[reportArgumentType]
    return [f for f in values.finding_list(user, year).visible if f.kind in (PENDING, DUPLICATE)]


# --- Eintragsart ------------------------------------------------------------------------------


def test_end_year_before_start_is_invalid() -> None:
    try:
        expected(2025, 2024)
    except ValueError:
        return
    raise AssertionError("Endjahr vor Beginn muss abgelehnt werden")


def test_due_in_respects_start_and_open_end() -> None:
    entry = expected(2024)
    assert not entry.due_in(2023) and entry.due_in(2024) and entry.due_in(2040)
    assert not expected(2024, 2024).due_in(2025)


# --- Befunde ----------------------------------------------------------------------------------


def test_without_document_the_year_is_pending_and_with_it_the_note_is_gone() -> None:
    entry = expected()
    (found,) = findings([entry])
    assert found.kind == PENDING and found.target == f"{entry.address}@2025"
    assert "2025" in found.message and "ausstehend" in found.message
    assert findings([entry, document(2025)]) == []


def test_two_matching_documents_make_a_possible_duplicate() -> None:
    entry = expected()
    (found,) = findings([entry, document(2025), document(2025, sha="b" * 64)])
    assert found.kind == DUPLICATE and "Dublette" in found.message


def test_duplicate_fingerprint_changes_with_the_documents() -> None:
    entry = expected()
    first = findings([entry, document(2025), document(2025, sha="b" * 64)])[0]
    second = findings(
        [entry, document(2025), document(2025, sha="b" * 64), document(2025, sha="c" * 64)]
    )[0]
    assert first.fingerprint != second.fingerprint


def test_end_year_2024_gives_no_note_for_2025() -> None:
    assert findings([expected(2023, 2024)]) == []
    assert findings([expected(2026)]) == []


def test_only_matching_kind_year_and_owner_fulfil() -> None:
    entry = expected()
    for other in (
        document(2024),
        document(None),
        document(2025, kind="anderes.dokument"),
        document(2025, owner="berta"),
    ):
        assert [f.kind for f in findings([entry, other])] == [PENDING]


def test_other_users_see_only_their_own_expected_documents() -> None:
    assert findings([expected(owner="berta")]) == []


def test_each_year_is_its_own_finding() -> None:
    entry = expected(2025)
    assert findings([entry], 2025)[0].identity != findings([entry], 2026)[0].identity


# --- Fundstelle -------------------------------------------------------------------------------


def test_a_value_with_expected_document_locator_is_pending() -> None:
    key = ValueKey("demo.interest")
    entry = expected()

    def compute(calculation: Calculation) -> Amount:
        amount = Amount.eur_cents(12300)
        calculation.item(
            "Zinsen laut Erwartetem Beleg", amount, ExpectedDocumentLocator(entry.address)
        )
        return calculation.step("Zinsen", amount)

    module = ModuleRegistration(
        key="demo",
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        values=(ValueDefinition(CatalogEntry(key, "Zinsen", Unit.EUR, TimeKind.PERIOD), compute),),
    )

    result = evaluate([module], [entry]).get(key, "anna", Period.year(2025))

    assert isinstance(result, ExposedValue)
    assert result.backing is Backing.PENDING
    assert result.items[0].locator.entry_address == entry.address


# --- Seite ------------------------------------------------------------------------------------


def make_client(root: Path, user: str = "anna") -> httpx.Client:
    app = create_app(PORT, root, modules=[WORK, TAX_YEAR], user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def stored(root: Path) -> list[ExpectedDocument]:
    return open_store(root, []).state().of_kind(ExpectedDocument)


FORM = {"document_kind": KIND, "start_year": "2025", "end_year": "", "description": "Beispiel"}


def test_create_lists_status_per_year(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/erwartete-belege", data=FORM, headers=ORIGIN)

    assert response.status_code == 303
    (entry,) = stored(tmp_path)
    assert entry.end_year is None and entry.owner == "anna"
    page = client.get("/erwartete-belege").text
    assert "Übertragungsprotokoll" in page and "ausstehend" in page
    open_store(tmp_path, []).apply([Put(document(2025))])
    assert "erfüllt durch" in make_client(tmp_path).get("/erwartete-belege").text


def test_pending_note_shows_on_findings_page_with_link(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/erwartete-belege", data=FORM, headers=ORIGIN)

    page = client.get("/befunde?year=2025").text

    assert "Erwarteter Beleg für 2025 ausstehend" in page
    assert 'href="/erwartete-belege"' in page


def test_invalid_input_is_rejected_with_hints(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    for bad in (
        {**FORM, "document_kind": "gibt.es.nicht"},
        {**FORM, "start_year": "abc"},
        {**FORM, "end_year": "2024"},
    ):
        response = client.post("/erwartete-belege", data=bad, headers=ORIGIN)
        assert response.status_code == 422 and 'class="fehler"' in response.text
    assert stored(tmp_path) == []


def test_update_and_delete_use_the_checksum(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/erwartete-belege", data=FORM, headers=ORIGIN)
    (entry,) = stored(tmp_path)
    edit = client.get(f"/erwartete-belege/{entry.id}").text
    checksum = re.search(r'name="checksum" value="([0-9a-f]+)"', edit)
    assert checksum

    changed = {**FORM, "end_year": "2027", "checksum": checksum.group(1)}
    assert (
        client.post(f"/erwartete-belege/{entry.id}", data=changed, headers=ORIGIN).status_code
        == 303
    )
    assert stored(tmp_path)[0].end_year == 2027

    stale = client.post(f"/erwartete-belege/{entry.id}", data=changed, headers=ORIGIN)
    assert stale.status_code == 409 and stored(tmp_path)[0].end_year == 2027
    gone = client.post(
        f"/erwartete-belege/{entry.id}/loeschen", data={"checksum": "alt"}, headers=ORIGIN
    )
    assert gone.status_code == 409 and len(stored(tmp_path)) == 1

    fresh = re.search(
        r'name="checksum" value="([0-9a-f]+)"', client.get(f"/erwartete-belege/{entry.id}").text
    )
    assert fresh
    done = client.post(
        f"/erwartete-belege/{entry.id}/loeschen", data={"checksum": fresh.group(1)}, headers=ORIGIN
    )
    assert done.status_code == 303 and stored(tmp_path) == []


def test_another_user_cannot_open_the_entry(tmp_path: Path) -> None:
    make_client(tmp_path).post("/erwartete-belege", data=FORM, headers=ORIGIN)
    (entry,) = stored(tmp_path)

    other = make_client(tmp_path, user="berta")

    assert other.get(f"/erwartete-belege/{entry.id}").status_code == 404
    assert EntryAddress.parse(str(entry.address)) == entry.address


def test_kinds_without_period_are_not_offered() -> None:
    plain = DocumentKind("demo.vertrag", "Vertrag", False, lambda d, b: [])
    assert not plain.has_period


def test_hiding_pending_2025_leaves_2026_a_separate_finding(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/erwartete-belege", data=FORM, headers=ORIGIN)
    (entry,) = stored(tmp_path)
    found = findings([entry], 2025)[0]
    form = {
        "year": "2025",
        "kind": found.kind,
        "target": found.identity[1],
        "fingerprint": found.fingerprint,
        "note": "Kommt später.",
    }
    assert client.post("/befunde/ausblenden", data=form, headers=ORIGIN).status_code == 303

    state = open_store(tmp_path, []).state()
    values = evaluate([WORK, TAX_YEAR], list(state.entries.values()))
    list_2025 = values.finding_list("anna", 2025)
    list_2026 = evaluate([WORK, TAX_YEAR], list(state.entries.values())).finding_list("anna", 2026)

    assert [h.finding.kind for h in list_2025.hidden] == [PENDING]
    assert [f.kind for f in list_2025.visible if f.kind == PENDING] == []
    (visible,) = [f for f in list_2026.visible if f.kind == PENDING]
    assert visible.identity[1] == f"{entry.address}@2026"
    assert visible.identity not in list_2026.earlier


def test_changing_the_description_brings_a_hidden_pending_finding_back(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/erwartete-belege", data=FORM, headers=ORIGIN)
    (entry,) = stored(tmp_path)
    found = findings([entry], 2025)[0]
    form = {
        "year": "2025",
        "kind": found.kind,
        "target": found.identity[1],
        "fingerprint": found.fingerprint,
        "note": "Kommt später.",
    }
    client.post("/befunde/ausblenden", data=form, headers=ORIGIN)
    store = open_store(tmp_path, [])
    renamed = entry.model_copy(update={"description": "Anderes Beispiel"})
    store.apply([Put(renamed, expected=store.state().checksum(entry.address))])

    state = open_store(tmp_path, []).state()
    listed = evaluate([WORK, TAX_YEAR], list(state.entries.values())).finding_list("anna", 2025)
    assert [f.kind for f in listed.visible if f.kind == PENDING] == [PENDING]


# --- Aussteller des Vorjahres als Vorschlag ---------------------------------------------------


def issued_by(at: Issuer, year: int = 2024, sha: str = SHA) -> Document:
    return document(year, sha=sha).model_copy(update={"issuer": at.address})


def test_suggestion_is_issuer_of_the_document_fulfilling_the_previous_year() -> None:
    bank = Issuer(owner=COMMON_OWNER, name="Beispielbank")
    entry = expected(start=2024)

    assert previous_year_issuer([issued_by(bank)], entry, 2025) == bank.address
    assert previous_year_issuer([issued_by(bank)], entry, 2024) is None  # Vorjahr vor Beginn
    assert previous_year_issuer([issued_by(bank)], entry, 2026) is None  # Vorjahr nicht erfüllt
    assert previous_year_issuer([document(2024)], entry, 2025) is None  # ohne Aussteller


def test_a_document_with_another_issuer_still_fulfils() -> None:
    bank = Issuer(owner=COMMON_OWNER, name="Beispielbank")
    other = Issuer(owner=COMMON_OWNER, name="Andere Bank")
    documents = [issued_by(bank), issued_by(other, 2025, "b" * 64)]
    entry = expected(start=2024)

    assert len(matching_documents(documents, entry, 2025)) == 1
    assert findings([entry, *documents]) == []


def test_pages_show_the_suggestion_and_follow_a_merge(tmp_path: Path) -> None:
    source = Issuer(owner=COMMON_OWNER, name="Beispielbank")
    target = Issuer(owner=COMMON_OWNER, name="Beispielbank AG")
    entry = expected(start=2024)
    store = open_store(tmp_path, [])
    store.apply([Put(source), Put(target), Put(entry), Put(issued_by(source))])
    client = make_client(tmp_path)

    for url in ("/erwartete-belege", f"/erwartete-belege/{entry.id}"):
        page = client.get(url).text
        assert f'Aussteller im Vorjahr: <a href="{source.url}">Beispielbank</a>' in page

    state = store.state()
    store.apply(
        [
            Merge(
                source.address,
                target.address,
                expected=state.checksum(source.address) or "",
                expected_into=state.checksum(target.address) or "",
            )
        ]
    )
    page = make_client(tmp_path).get("/erwartete-belege").text
    assert f'<a href="{target.url}">Beispielbank AG</a>' in page


def test_pages_show_no_suggestion_without_issuer(tmp_path: Path) -> None:
    open_store(tmp_path, []).apply([Put(expected(start=2024)), Put(document(2024))])

    assert "Aussteller im Vorjahr" not in make_client(tmp_path).get("/erwartete-belege").text
