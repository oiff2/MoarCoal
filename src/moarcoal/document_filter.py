"""Zustand und Filter der Dokumente (Reiter Dokumente): bei jeder Anfrage abgeleitet, nie
gespeichert."""

from collections.abc import Mapping
from enum import StrEnum

from moarcoal.documents import DocumentKind
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import Document, Issuer, State, name_key

WITHOUT_KIND = "none"
"""Filterwert für „Beleg“: Dokumente ohne Dokumentart."""

WITHOUT_ISSUER = "none"
"""Filterwert für „ohne Aussteller“."""


class DocumentState(StrEnum):
    """Der abgeleitete Zustand eines Dokuments, in der Reihenfolge des Filters; ohne Art `BELEG`."""

    TO_CONFIRM = "zu bestätigen"
    TO_EXTRACT = "auszulesen"
    DONE = "fertig"
    BELEG = "Beleg"


def document_state(
    state: State, kinds: Mapping[str, DocumentKind], document: Document
) -> DocumentState:
    """„zu bestätigen“ (der neueste Vorschlag hat offene Felder), „auszulesen“ (die Art hat eine
    Auslese-Vorlage, aber es gibt keinen Vorschlag), „fertig“ oder, ohne Art, „Beleg“ (neutral)."""
    if not document.document_kind:
        return DocumentState.BELEG
    proposal = latest_proposal(state, document)
    if proposal is not None:
        return DocumentState.TO_CONFIRM if proposal.open_keys else DocumentState.DONE
    if template_of(kinds, document) is not None:
        return DocumentState.TO_EXTRACT
    return DocumentState.DONE


def filter_documents(
    state: State,
    user: str,
    kinds: Mapping[str, DocumentKind],
    *,
    kind: str = "",
    year: int | None = None,
    issuer: str = "",
    query: str = "",
    status: str = "",
) -> list[Document]:
    """Die Dokumente von `user`, die alle gesetzten Filter erfüllen, nach Pfad sortiert.

    `kind` ist ein Schlüssel oder `WITHOUT_KIND`, `issuer` eine Kennung oder `WITHOUT_ISSUER`,
    `status` ein Zustand aus `document_state`, leer jeweils für alle; `year` trifft Dokumente,
    deren Bezugszeitraum das Jahr berührt; `query` sucht ohne Groß-/Kleinschreibung in Pfad,
    Ablageort, Art und Namen und Aliassen des Ausstellers.
    """
    issuers = {i.address: i for i in state.of_kind(Issuer)}
    needle = name_key(query)
    found: list[Document] = []
    for document in state.of_kind(Document):
        if document.owner != user:
            continue
        if kind and (document.document_kind or WITHOUT_KIND) != kind:
            continue
        if issuer and (document.issuer.id if document.issuer else WITHOUT_ISSUER) != issuer:
            continue
        if year is not None and not document.touches_year(year):
            continue
        if status and document_state(state, kinds, document) != status:
            continue
        owner = issuers.get(document.issuer) if document.issuer else None
        kind_entry = kinds.get(document.document_kind or "")
        texts = [document.site, document.path, kind_entry.title if kind_entry else ""]
        texts += [owner.name, *owner.aliases] if owner else []
        if needle and not any(needle in name_key(text) for text in texts):
            continue
        found.append(document)
    return sorted(found, key=lambda d: (d.path, d.site, d.id))
