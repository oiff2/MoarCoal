"""Seite „Aussteller“: Katalog, Suche, Detail, Ändern, Löschen (nur tmp_path)."""

import re
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.storage import COMMON_OWNER, Document, Issuer, Put, open_store

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
SHA = "b" * 64


def make_client(root: Path, user: str = "anna") -> httpx.Client:
    app = make_app(PORT, root, modules=[WORK, TAX_YEAR], user=user)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def issuer(name: str = "Beispielbank AG", **fields: object) -> Issuer:
    return Issuer(owner=COMMON_OWNER, name=name, **fields)  # pyright: ignore[reportArgumentType]


def document(at: Issuer | None, owner: str = "anna", sha: str = SHA) -> Document:
    return Document(
        owner=owner,
        site="Ablage",
        path=f"{sha[:4]}.pdf",
        sha256=sha,
        issuer=None if at is None else at.address,
    )


def put(root: Path, *entries: Issuer | Document) -> None:
    open_store(root, []).apply([Put(e) for e in entries])


def stored(root: Path) -> list[Issuer]:
    return open_store(root, []).state().of_kind(Issuer)


def checksum_of(page: str) -> str:
    found = re.search(r'name="checksum" value="([0-9a-f]+)"', page)
    assert found
    return found.group(1)


def test_catalog_lists_name_aliases_counts_and_searches(tmp_path: Path) -> None:
    bank = issuer(aliases=("Beispielbank", "BB"))
    amt = issuer("Musterfinanzamt")
    put(tmp_path, bank, amt, document(bank), document(bank, sha="c" * 64))
    client = make_client(tmp_path)

    page = client.get("/aussteller").text

    assert "Beispielbank AG" in page and "Musterfinanzamt" in page
    assert "Beispielbank, BB" in page and f'href="/aussteller/{bank.id}"' in page
    assert re.search(r"Beispielbank AG</a>.*?<td>2</td>\s*<td>0</td>", page, re.S)
    assert "Musterfinanzamt" not in client.get("/aussteller?q=beispielbank").text
    assert "BB" in client.get("/aussteller?q=bb").text
    assert "Kein Aussteller" in client.get("/aussteller?q=gibtesnicht").text
    assert 'href="/aussteller"' in client.get("/").text  # Eintrag in der Navigation


def test_detail_shows_documents_and_change_keeps_the_address(tmp_path: Path) -> None:
    bank = issuer()
    put(tmp_path, bank, document(bank))
    client = make_client(tmp_path)

    page = client.get(f"/aussteller/{bank.id}").text
    assert "Ablage: bbbb.pdf" in page and "Keine Erwarteten Belege" in page

    form = {
        "name": "Beispielbank Gruppe",
        "aliases": "Beispielbank\r\n\r\n BB ",
        "private_person": "on",
        "checksum": checksum_of(page),
    }
    response = client.post(f"/aussteller/{bank.id}", data=form, headers=ORIGIN)

    assert response.status_code == 303
    (changed,) = stored(tmp_path)
    assert changed.id == bank.id and changed.name == "Beispielbank Gruppe"
    assert changed.aliases == ("Beispielbank", "BB") and changed.private_person
    stale = client.post(f"/aussteller/{bank.id}", data=form, headers=ORIGIN)
    assert stale.status_code == 409 and 'class="fehler"' in stale.text


def test_invalid_change_is_rejected_with_a_hint(tmp_path: Path) -> None:
    bank = issuer()
    put(tmp_path, bank)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{bank.id}").text

    response = client.post(
        f"/aussteller/{bank.id}",
        data={"name": "  ", "checksum": checksum_of(page)},
        headers=ORIGIN,
    )

    assert response.status_code == 422 and "Name: darf nicht leer sein" in response.text
    assert stored(tmp_path) == [bank]


def test_change_to_a_taken_name_is_rejected_with_the_reason(tmp_path: Path) -> None:
    bank, werke = issuer(), issuer("Stadtwerke Beispielstadt")
    put(tmp_path, bank, werke)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{werke.id}").text

    response = client.post(
        f"/aussteller/{werke.id}",
        data={"name": werke.name, "aliases": "beispielbank ag", "checksum": checksum_of(page)},
        headers=ORIGIN,
    )

    assert response.status_code == 409
    assert f'Duplikat zu: <a href="/aussteller/{bank.id}">{bank.name}</a>' in (response.text)
    assert sorted(i.name for i in stored(tmp_path)) == sorted([bank.name, werke.name])


def test_change_to_a_taken_name_names_the_other_issuer(tmp_path: Path) -> None:
    bank, werke = issuer(), issuer("Stadtwerke Beispielstadt")
    put(tmp_path, bank, werke)
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{werke.id}").text

    response = client.post(
        f"/aussteller/{werke.id}",
        data={"name": bank.name.upper(), "checksum": checksum_of(page)},
        headers=ORIGIN,
    )

    assert response.status_code == 409 and f"/aussteller/{bank.id}" in response.text


def test_delete_only_without_references(tmp_path: Path) -> None:
    bank = issuer()
    put(tmp_path, bank, document(bank))
    client = make_client(tmp_path)
    page = client.get(f"/aussteller/{bank.id}").text
    assert "/loeschen" not in page and "wird noch verwendet" in page

    refused = client.post(
        f"/aussteller/{bank.id}/loeschen", data={"checksum": checksum_of(page)}, headers=ORIGIN
    )
    assert refused.status_code == 409 and "Wird noch verwendet." in refused.text
    assert stored(tmp_path) == [bank]

    free = issuer("Musterfinanzamt")
    put(tmp_path, free)
    other = make_client(tmp_path)
    free_page = other.get(f"/aussteller/{free.id}").text
    done = other.post(
        f"/aussteller/{free.id}/loeschen",
        data={"checksum": checksum_of(free_page)},
        headers=ORIGIN,
    )
    assert done.status_code == 303 and stored(tmp_path) == [bank]


def test_unknown_issuer_is_not_found(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/aussteller/gibtesnicht").status_code == 404
    assert client.get("/aussteller/..%2Fx").status_code == 404


def test_private_person_stays_out_of_findings(tmp_path: Path) -> None:
    landlord = issuer("Erika Beispielfrau", private_person=True)
    put(tmp_path, landlord, document(landlord), document(None, sha="d" * 64))
    client = make_client(tmp_path)

    findings = client.get("/befunde?year=2025").text

    assert "Dokument ohne Aussteller" in findings and "Beispielfrau" not in findings
    assert "Beispielfrau" in client.get("/aussteller").text
