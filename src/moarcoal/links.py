"""Adressen der Seiten zu den Bausteinen der Datenebene (die Datenebene kennt keine Routen)."""


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: der Reiter Dokumente, das Dokument gewählt."""
    return f"/belege/dokumente?dokument={document_id}"


def issuer_url(issuer_id: str) -> str:
    return f"/aussteller/{issuer_id}"
