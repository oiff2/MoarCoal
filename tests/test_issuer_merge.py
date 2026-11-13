"""Aussteller zusammenführen: Vorgang der Datenebene und Seite (nur tmp_path)."""

import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Document,
    Issuer,
    Merge,
    Put,
    Rejected,
    Store,
    entry_checksum,
    open_store,
)

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


def issuer(name: str, **fields: object) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, **fields)  # pyright: ignore[reportArgumentType]


def document(at: Issuer, owner: str = "anna", sha: str = "a" * 64) -> Document:
    return Document(
        owner=owner, site="Ablage", path=f"{sha[:4]}.pdf", sha256=sha, issuer=at.address
    )


def merge_of(store: Store, source: Issuer, into: Issuer) -> Merge:
    state = store.state()
    return Merge(
        source.address,
        into.address,
        expected=state.checksum(source.address) or "",
        expected_into=state.checksum(into.address) or "",
    )


def stored(root: Path) -> list[Issuer]:
    return open_store(root, []).state().of_kind(Issuer)


def test_merge_moves_names_references_and_old_address_resolves(tmp_path: Path) -> None:
    source = issuer("Beispielbank", aliases=("BB",), private_person=True)
    target = issuer("Beispielbank AG", aliases=("beispielbank",))
    store = open_store(tmp_path, [])
    store.apply(
        [
            Put(source),
            Put(target),
            Put(document(source)),
            Put(document(source, owner="ben", sha="b" * 64)),
        ]
    )

    result = store.apply([merge_of(store, source, target)])

    assert isinstance(result, Applied)
    state = open_store(tmp_path, []).state()  # nach dem Neuladen
    assert state.get(source.address) is None
    merged = state.get(target.address)
    assert isinstance(merged, Issuer)
    assert merged.aliases == ("beispielbank", "BB")  # "Beispielbank" ist schon Alias (Groß/klein)
    assert merged.private_person
    assert state.resolve(source.address) == merged
    assert [d.issuer for d in state.of_kind(Document)] == [target.address] * 2


def test_merge_is_all_or_nothing(tmp_path: Path) -> None:
    source, target = issuer("Alt"), issuer("Neu")
    store = open_store(tmp_path, [])
    store.apply([Put(source), Put(target), Put(document(source))])
    before = (tmp_path / "common/issuers.json").read_bytes()

    result = store.apply([Merge(source.address, target.address, expected="x", expected_into="y")])

    assert isinstance(result, Rejected)
    assert (tmp_path / "common/issuers.json").read_bytes() == before
    assert store.state().get(source.address) is not None


def test_merge_rejects_itself_and_other_kinds(tmp_path: Path) -> None:
    one = issuer("Eins")
    doc = document(one)
    store = open_store(tmp_path, [])
    store.apply([Put(one), Put(doc)])

    same = store.apply([merge_of(store, one, one)])
    other = store.apply([Merge(doc.address, one.address, "a", "b")])

    assert isinstance(same, Rejected)
    assert isinstance(other, Rejected)


# --- Seite ----------------------------------------------------------------------------------


def make_client(root: Path) -> httpx.Client:
    app = create_app(PORT, root, modules=[WORK, TAX_YEAR], user="anna")
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def form(page: str, **extra: str) -> dict[str, str]:
    found = {
        name: match.group(1)
        for name in ("into", "checksum", "target_checksum")
        if (match := re.search(rf'name="{name}" value="([^"]+)"', page))
    }
    return {**found, **extra}


def two_issuers(root: Path) -> tuple[Issuer, Issuer]:
    source, target = issuer("Beispielbank"), issuer("Beispielbank AG")
    open_store(root, []).apply([Put(source), Put(target), Put(document(source))])
    return source, target


def test_preview_shows_consequences_and_changes_nothing(tmp_path: Path) -> None:
    source, target = two_issuers(tmp_path)
    client = make_client(tmp_path)

    detail = client.get(f"/aussteller/{source.id}").text
    page = client.get(f"/aussteller/{source.id}/zusammenfuehren?into={target.id}")

    assert f'value="{target.id}"' in detail
    assert page.status_code == 200
    assert "Betroffene Dokumente (1)" in page.text
    assert len(stored(tmp_path)) == 2


def test_merge_needs_confirmation(tmp_path: Path) -> None:
    source, target = two_issuers(tmp_path)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{source.id}/zusammenfuehren?into={target.id}").text

    response = client.post(
        f"/aussteller/{source.id}/zusammenfuehren", data=form(page), headers=ORIGIN
    )

    assert response.status_code == 422
    assert len(stored(tmp_path)) == 2


def test_merge_confirmed_and_old_address_redirects(tmp_path: Path) -> None:
    source, target = two_issuers(tmp_path)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{source.id}/zusammenfuehren?into={target.id}").text

    response = client.post(
        f"/aussteller/{source.id}/zusammenfuehren",
        data=form(page, confirm="on"),
        headers=ORIGIN,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/aussteller/{target.id}"
    assert [i.id for i in stored(tmp_path)] == [target.id]
    old = client.get(f"/aussteller/{source.id}")
    assert old.status_code == 308
    assert old.headers["location"] == f"/aussteller/{target.id}"
    assert "Beispielbank" in client.get(f"/aussteller/{target.id}").text


def test_merge_with_stale_checksum_is_rejected(tmp_path: Path) -> None:
    source, target = two_issuers(tmp_path)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{source.id}/zusammenfuehren?into={target.id}").text
    changed = target.model_copy(update={"aliases": ("BB",)})
    open_store(tmp_path, []).apply([Put(changed, expected=entry_checksum(target))])

    response = client.post(
        f"/aussteller/{source.id}/zusammenfuehren",
        data=form(page, confirm="on"),
        headers=ORIGIN,
    )

    assert response.status_code == 409
    assert len(stored(tmp_path)) == 2
