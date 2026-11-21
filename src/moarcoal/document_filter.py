"""Zustand der Dokumente (Belege-Seite): bei jeder Anfrage abgeleitet, nie gespeichert."""

from collections.abc import Mapping
from enum import StrEnum

from moarcoal.documents import DocumentKind
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import Document, State


class DocumentState(StrEnum):
    """Der abgeleitete Zustand eines Dokuments; ohne Art `BELEG`."""

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
