"""Seite „Belege“, Reiter Dokumente: alle aufgenommenen Dokumente mit Filter und Suche.

Der Zustand eines Dokuments wird bei jeder Anfrage abgeleitet und nicht gespeichert. Ändern und
Löschen laufen über die Routen unter `/dokumente/{id}` (`document_pages.py`).
"""

from collections.abc import Mapping
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import DocumentKind, references_to
from moarcoal.previews import preview_kind
from moarcoal.proposals import proposals_of
from moarcoal.storage import Document, Issuer, State, entry_checksum, name_key
from moarcoal.web import document_kinds, render, store_of, user_of

router = APIRouter(prefix="/belege/dokumente")

NONE = "none"
"""Filterwert für „ohne Art“ und „ohne Aussteller“."""

REFERENCE_LABELS = {
    "Proposal": "Vorschlag",
    "AbortedExtraction": "Abgebrochene Auslesung",
    "Snapshot": "Schnappschuss",
    "ProtocolReading": "Einlesung",
}
"""Bezeichnungen für die Einträge, die auf ein Dokument verweisen; sonst gilt der Name im Code."""


def document_state(state: State, document: Document) -> str:
    """„zu bestätigen“ (der neueste Vorschlag hat offene Felder), „fertig“ oder, ohne Art,
    „ohne Art“ (neutral)."""
    if not document.document_kind:
        return "ohne Art"
    proposals = proposals_of(state, document)
    return "zu bestätigen" if proposals and proposals[-1].open_keys else "fertig"


def filter_documents(
    state: State,
    user: str,
    kinds: Mapping[str, DocumentKind],
    *,
    kind: str = "",
    year: int | None = None,
    issuer: str = "",
    query: str = "",
) -> list[Document]:
    """Die Dokumente von `user`, die alle gesetzten Filter erfüllen, nach Pfad sortiert.

    `kind` und `issuer` sind ein Schlüssel bzw. eine Kennung, `NONE` für „ohne“, leer für alle;
    `year` trifft Dokumente, deren Bezugszeitraum das Jahr berührt; `query` sucht ohne Groß-/
    Kleinschreibung in Pfad, Ablageort, Art und Namen und Aliassen des Ausstellers.
    """
    issuers = {i.address: i for i in state.of_kind(Issuer)}
    needle = name_key(query)
    found: list[Document] = []
    for document in state.of_kind(Document):
        if document.owner != user:
            continue
        if kind and (document.document_kind or NONE) != kind:
            continue
        if issuer and (document.issuer.id if document.issuer else NONE) != issuer:
            continue
        if year is not None and not (
            document.period_start
            and document.period_end
            and document.period_start.year <= year <= document.period_end.year
        ):
            continue
        owner = issuers.get(document.issuer) if document.issuer else None
        kind_entry = kinds.get(document.document_kind or "")
        texts = [document.site, document.path, kind_entry.title if kind_entry else ""]
        texts += [owner.name, *owner.aliases] if owner else []
        if needle and not any(needle in name_key(text) for text in texts):
            continue
        found.append(document)
    return sorted(found, key=lambda d: (d.path, d.site, d.id))


def _year_of(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    art: str = "",
    jahr: str = "",
    aussteller: str = "",
    dokument: str = "",
) -> HTMLResponse:
    store = store_of(request)
    state = store.state()
    kinds = document_kinds(request)
    documents = filter_documents(
        state,
        user_of(request),
        kinds,
        kind=art,
        year=_year_of(jahr),
        issuer=aussteller,
        query=q,
    )
    chosen = next((d for d in documents if d.id == dokument), None)
    issuers = {i.id: i for i in state.of_kind(Issuer)}
    filters = {"q": q, "art": art, "jahr": jahr, "aussteller": aussteller}
    return render(
        request,
        "documents/list.html",
        documents=documents,
        states={d.id: document_state(state, d) for d in documents},
        selected=chosen,
        references=references_to(state, chosen) if chosen else [],
        checksum=entry_checksum(chosen) if chosen else "",
        issuer=issuers.get(chosen.issuer.id) if chosen and chosen.issuer else None,
        issuer_names={i.id: i.name for i in issuers.values()},
        issuer_list=sorted(issuers.values(), key=lambda i: name_key(i.name)),
        kinds=list(kinds.values()),
        kind_titles={k.key: k.title for k in kinds.values()},
        filters=filters,
        base=urlencode({k: v for k, v in filters.items() if v}),
        preview_kind=chosen and preview_kind(chosen.path),
        preview_url=chosen and f"/dokumente/{chosen.id}/datei",
        default_year=DEFAULT_YEAR,
        labels=REFERENCE_LABELS,
        none=NONE,
    )
