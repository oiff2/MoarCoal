"""Tests: Vorschau der Belege, Datei-Routen mit Schutz-Headern, weiter zur nächsten Datei."""

import hashlib
from pathlib import Path
from typing import cast

import httpx
import pytest
from test_belege import FIXTURE, ORIGIN, SHA, make_client, take

from moarcoal.incoming import Folder, Row, next_open
from moarcoal.storage import Document, Put, SiteFile, Store, entry_checksum

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PDF = b"%PDF-1.4\n% Beispiel\n"


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    (folder / "2025").mkdir(parents=True)
    (folder / "2025" / "protokoll.html").write_bytes(FIXTURE.read_bytes())
    (folder / "bild.png").write_bytes(PNG)
    (folder / "scan.pdf").write_bytes(PDF)
    (folder / "notiz.txt").write_text("Beispiel", encoding="utf-8")
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "daten"


def store_of(client: httpx.Client) -> Store:
    return cast(Store, client.app.state.store)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def document_of(client: httpx.Client) -> Document:
    store = store_of(client)
    (document,) = store.state().of_kind(Document)
    return document


# --- Datei-Route der Ablage ----------------------------------------------------------------------


def test_html_is_served_sandboxed_without_script_and_nosniff(root: Path, site: Path) -> None:
    response = make_client(root, site).get(f"/belege/datei/{SHA}")
    assert response.status_code == 200
    assert response.content == FIXTURE.read_bytes()
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "sandbox" in csp.split("; ") and "allow-scripts" not in csp
    assert "default-src 'none'" in csp
    assert "script-src" not in csp or "'unsafe-inline'" not in csp.split("script-src")[1]
    assert "frame-ancestors 'self'" in csp


def test_pdf_and_image_have_their_media_type_and_may_only_be_framed_by_the_app(
    root: Path, site: Path
) -> None:
    client = make_client(root, site)
    pdf = client.get(f"/belege/datei/{sha(PDF)}")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-security-policy"] == "frame-ancestors 'self'"
    image = client.get(f"/belege/datei/{sha(PNG)}")
    assert image.headers["content-type"] == "image/png"
    assert "default-src 'none'" in image.headers["content-security-policy"]
    for response in (pdf, image):
        assert response.headers["x-content-type-options"] == "nosniff"


def test_file_without_preview_is_refused(root: Path, site: Path) -> None:
    response = make_client(root, site).get(f"/belege/datei/{sha(b'Beispiel')}")
    assert response.status_code == 415
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("sha256", ["0" * 64, "..%2F..%2Fetc%2Fpasswd", "/etc/passwd", "x"])
def test_unknown_sha256_and_paths_are_refused(root: Path, site: Path, sha256: str) -> None:
    assert make_client(root, site).get(f"/belege/datei/{sha256}").status_code == 404


def test_link_leaving_the_site_is_not_served(root: Path, site: Path, tmp_path: Path) -> None:
    outside = tmp_path / "geheim.html"
    outside.write_text("<p>geheim</p>", encoding="utf-8")
    (site / "link.html").symlink_to(outside)
    response = make_client(root, site).get(f"/belege/datei/{sha(outside.read_bytes())}")
    assert response.status_code == 404


def test_get_of_a_file_never_writes(root: Path, site: Path) -> None:
    client = make_client(root, site)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    client.get(f"/belege/datei/{SHA}")
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


# --- Datei-Route eines Dokuments -----------------------------------------------------------------


def test_document_file_is_served_like_the_site_file(root: Path, site: Path) -> None:
    client = make_client(root, site)
    take(client)
    response = client.get(f"/dokumente/{document_of(client).id}/datei")
    assert response.status_code == 200 and response.content == FIXTURE.read_bytes()
    assert "sandbox" in response.headers["content-security-policy"].split("; ")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_document_file_unknown_id_or_changed_content_is_404(root: Path, site: Path) -> None:
    client = make_client(root, site)
    take(client)
    assert client.get("/dokumente/gibt-es-nicht/datei").status_code == 404
    (site / "2025" / "protokoll.html").write_text("<p>anderer Inhalt</p>", encoding="utf-8")
    assert client.get(f"/dokumente/{document_of(client).id}/datei").status_code == 404


@pytest.mark.parametrize("path", ["../bild.png", "/tmp/bild.png", "2025/../bild.png"])
def test_document_file_with_unsafe_path_is_404(root: Path, site: Path, path: str) -> None:
    client = make_client(root, site)
    take(client)
    document = document_of(client)
    tampered = document.model_copy(update={"path": path, "sha256": sha(PNG)})
    store = store_of(client)
    store.apply([Put(tampered, entry_checksum(document))])
    assert client.get(f"/dokumente/{document.id}/datei").status_code == 404


# --- Seite ---------------------------------------------------------------------------------------


def preview_page(client: httpx.Client, content: bytes) -> str:
    return client.get(f"/belege?datei={sha(content)}").text


def test_page_embeds_html_in_a_sandbox_without_permissions(root: Path, site: Path) -> None:
    page = preview_page(make_client(root, site), FIXTURE.read_bytes())
    assert f'<iframe src="/belege/datei/{SHA}" title="Vorschau" sandbox="">' in page
    assert "allow-" not in page


def test_page_embeds_pdf_and_image_and_says_so_without_preview(root: Path, site: Path) -> None:
    client = make_client(root, site)
    assert f'<iframe src="/belege/datei/{sha(PDF)}" title="Vorschau">' in preview_page(client, PDF)
    assert f'<img src="/belege/datei/{sha(PNG)}"' in preview_page(client, PNG)
    page = preview_page(client, b"Beispiel")
    assert "Keine Vorschau." in page and "<iframe" not in page and "<img" not in page


def test_form_comes_before_the_preview_and_has_all_actions(root: Path, site: Path) -> None:
    page = preview_page(make_client(root, site), FIXTURE.read_bytes())
    main = page.split("<main>")[1]
    form, preview = main.index('class="formular"'), main.index('class="vorschau"')
    assert form < preview
    for part in ("Aufnehmen", "Ausblenden", 'name="kind"', 'name="year"', "issuer_text"):
        assert part in main[form:preview]


def test_page_without_choice_has_no_form_and_taken_file_links_its_document(
    root: Path, site: Path
) -> None:
    client = make_client(root, site)
    assert "Datei wählen" in client.get("/belege").text
    take(client)
    page = preview_page(client, FIXTURE.read_bytes())
    assert f"/dokumente/{document_of(client).id}/datei" in page
    assert "Aufnehmen</button>" not in page


def test_head_and_preview_scroll_on_their_own() -> None:
    css = Path("src/moarcoal/static/app.css").read_text(encoding="utf-8")
    assert ".formular { flex: 0 0 45%; overflow: auto; }" in css
    assert ".vorschau { flex: 1; min-height: 0; overflow: auto; }" in css
    assert "flex-direction: column; gap: 0.5rem; min-height: 0; }" in css


def test_no_choice_is_unselected_without_multiple_selection(root: Path, site: Path) -> None:
    page = make_client(root, site).get("/belege?datei=0000").text
    assert "Datei wählen" in page and 'type="checkbox"' not in page


# --- Weiter zur nächsten ---------------------------------------------------------------------


def location(response: httpx.Response) -> str:
    assert response.status_code == 303
    return response.headers["location"]


def test_taking_in_and_hiding_jump_to_the_next_open_file(root: Path, site: Path) -> None:
    client = make_client(root, site)
    # Reihenfolge der Anzeige: Ordner zuerst, dann Dateien nach Pfad
    assert location(take(client)) == f"/belege?datei={sha(PNG)}"
    hide = client.post("/belege/ausblenden", data={"sha256": sha(PNG)}, headers=ORIGIN)
    assert location(hide) == f"/belege?datei={sha(b'Beispiel')}"
    hide = client.post("/belege/ausblenden", data={"sha256": sha(b"Beispiel")}, headers=ORIGIN)
    assert location(hide) == f"/belege?datei={sha(PDF)}"
    last = client.post("/belege/ausblenden", data={"sha256": sha(PDF)}, headers=ORIGIN)
    assert location(last) == "/belege"


def test_without_another_open_file_taking_in_keeps_the_old_target(root: Path, site: Path) -> None:
    client = make_client(root, site)
    for name in ("bild.png", "scan.pdf", "notiz.txt"):
        (site / name).unlink()
    assert location(take(client)).startswith("/steuerjahr/uebertragungsprotokolle/")


def test_next_open_goes_on_and_wraps_around() -> None:
    def row(name: str) -> Row:
        return Row(SiteFile("Belege", name, 1, name * 64))

    root = Folder("Belege", rows=[row("a"), row("b"), row("c")])
    assert next_open([root], "a" * 64) == "b" * 64
    assert next_open([root], "c" * 64) == "a" * 64  # am Ende von vorn
    assert next_open([root], "x") == "a" * 64
    assert next_open([Folder("Belege", rows=[row("a")])], "a" * 64) is None
    assert next_open([], "a" * 64) is None


def test_keyboard_script_handles_arrows_and_enter() -> None:
    js = Path("src/moarcoal/static/belege.js").read_text(encoding="utf-8")
    assert "ArrowDown" in js and "ArrowUp" in js and '"Enter"' in js
