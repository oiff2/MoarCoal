"""Adressen der Seiten zu den Bausteinen der Datenebene (die Datenebene kennt keine Routen).

Wer außerhalb einer Routen-Angabe eine Adresse braucht (Befund, Seitenleiste, Vorschau), baut sie
hier; der Testkern weist Routen in `storage/` und `values/` ab.
"""


def site_url() -> str:
    """Die Belege-Seite, Reiter Ablage (der Eingang)."""
    return "/belege"


def site_file_url(sha256: str) -> str:
    """Eine Datei eines Ablageorts (Vorschau), erkannt am SHA-256."""
    return f"/belege/datei/{sha256}"


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: der Reiter Dokumente, das Dokument gewählt."""
    return f"/belege/dokumente?dokument={document_id}"


def document_file_url(document_id: str) -> str:
    """Die Datei eines Dokuments (Vorschau)."""
    return f"/dokumente/{document_id}/datei"


def expected_documents_url(expected_id: str | None = None) -> str:
    """Der Reiter Erwartet, mit `expected_id` der Erwartete Beleg gewählt."""
    return "/belege/erwartet" if expected_id is None else f"/belege/erwartet/{expected_id}"


def issuers_url() -> str:
    return "/aussteller"


def issuer_url(issuer_id: str) -> str:
    return f"/aussteller/{issuer_id}"
