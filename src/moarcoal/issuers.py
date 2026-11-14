"""Befund der Datenebene zum Aussteller (docs/grundgeruest.md, 3.2, Zuschnitt des Ausstellers)."""

from moarcoal.links import document_url
from moarcoal.storage import Document, State
from moarcoal.values.findings import Finding, Severity

DOCUMENT_WITHOUT_ISSUER = "document_without_issuer"


def issuer_findings(state: State, user: str) -> list[Finding]:
    """Hinweis je Dokument des Nutzers ohne Aussteller; der Link führt in den Reiter Dokumente."""
    documents = sorted(
        (d for d in state.of_kind(Document) if d.owner == user and d.issuer is None),
        key=lambda d: str(d.address),
    )
    return [
        Finding(
            DOCUMENT_WITHOUT_ISSUER,
            Severity.NOTE,
            d.address,
            f"Dokument ohne Aussteller: {d.path}",
            href=document_url(d.id),
        )
        for d in documents
    ]
