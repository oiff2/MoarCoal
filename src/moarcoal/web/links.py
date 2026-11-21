"""Adressen der Seiten zu den Bausteinen der Datenebene (die Datenebene kennt keine Routen).

Wer außerhalb einer Routen-Angabe eine Adresse braucht (Befund, Seitenleiste, Vorschau), baut sie
hier; der Testkern weist Routen in `storage/` und `values/` ab.
"""

from urllib.parse import urlencode


def site_url(*, document_kind: str | None = None, year: int | None = None) -> str:
    """Die Belege-Seite; mit `document_kind` (Schlüssel einer angemeldeten Dokumentart) und `year`
    ist das Aufnehmen-Formular so vorbelegt, und die Seite zeigt dieses Jahr."""
    query = urlencode(
        {
            name: value
            for name, value in (("dokumentart", document_kind), ("jahr", year))
            if value is not None
        }
    )
    return f"/belege?{query}" if query else "/belege"


def site_file_url(sha256: str) -> str:
    """Eine Datei eines Ablageorts (Vorschau), erkannt am SHA-256."""
    return f"/belege/datei/{sha256}"


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: die Belege-Seite, das Dokument gewählt."""
    return f"/belege?dokument={document_id}"


def document_file_url(document_id: str) -> str:
    """Die Datei eines Dokuments (Vorschau)."""
    return f"/dokumente/{document_id}/datei"


def expected_documents_url(expected_id: str | None = None) -> str:
    """Der Abschnitt Erwartete Belege der Belege-Seite; mit `expected_id` die Seite, auf der man
    den Erwarteten Beleg ändert."""
    return "/belege#erwartet" if expected_id is None else f"/belege/erwartet/{expected_id}"


def issuers_url() -> str:
    return "/aussteller"


def issuer_url(issuer_id: str) -> str:
    return f"/aussteller/{issuer_id}"
