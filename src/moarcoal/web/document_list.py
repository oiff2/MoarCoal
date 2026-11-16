"""Seite „Belege“, Reiter Dokumente: alle aufgenommenen Dokumente mit Filter und Suche.

Zustand und Filter stehen in `document_filter.py`, das Lesen von Art, Jahr und Aussteller in
`documents.py` (`read_document_choice`). Ändern und
Löschen laufen über die Routen unter `/dokumente/{id}` (`document_pages.py`); ihre Abweisungen
zeigt `documents_page` hier im Reiter.
"""

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from moarcoal.defaults import DEFAULT_YEAR, year_of
from moarcoal.document_filter import (
    WITHOUT_ISSUER,
    WITHOUT_KIND,
    DocumentState,
    document_state,
    filter_documents,
)
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import Document, Issuer, entry_checksum, name_key
from moarcoal.web.helpers import document_kinds, render, store_of, user_of
from moarcoal.web.links import document_file_url
from moarcoal.web.previews import preview_kind

router = APIRouter(prefix="/belege/dokumente")


def document_detail(
    request: Request, document: Document, issuer_text: str = "", year: str = ""
) -> dict[str, Any]:
    """Alles, was `documents/_detail.html` für den Kopf eines Dokuments braucht (Seite
    Reiter Dokumente und Ablage). `issuer_text` und `year` stellen eine
    abgewiesene Eingabe wieder her."""
    store = store_of(request)
    state = store.state()
    kinds = document_kinds(request)
    kind = kinds.get(document.document_kind or "")
    return {
        "document": document,
        "issuer": state.get(document.issuer) if document.issuer else None,
        "issuer_text": issuer_text,
        "year": year,
        "kinds": list(kinds.values()),
        "references": store.references_to(document.address),
        "bound": store.references_to(document.address, with_derived=True),
        "checksum": entry_checksum(document),
        "labels": store.kind_labels(),
        "default_year": DEFAULT_YEAR,
        "kind": kind,
        "template": template_of(kinds, document),
        "proposal": latest_proposal(state, document),
    }


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    art: str = "",
    jahr: str = "",
    aussteller: str = "",
    zustand: str = "",
    dokument: str = "",
) -> HTMLResponse:
    filters = {"q": q, "art": art, "jahr": jahr, "aussteller": aussteller, "zustand": zustand}
    return documents_page(request, filters=filters, selected=dokument)


def documents_page(
    request: Request,
    status_code: int = 200,
    *,
    filters: dict[str, str] | None = None,
    selected: str = "",
    notice: str = "",
    existing: Document | None = None,
    issuer_text: str = "",
    year: str = "",
) -> HTMLResponse:
    """Der Reiter Dokumente mit dem Dokument `selected` (Kennung) rechts. `notice` ist eine
    Abweisung (mit `existing`, dem vorhandenen Dokument bei „Existiert bereits“); `issuer_text`
    und `year` stellen die abgewiesene Eingabe wieder her."""
    filters = filters or dict.fromkeys(("q", "art", "jahr", "aussteller", "zustand"), "")
    store = store_of(request)
    state = store.state()
    kinds = document_kinds(request)
    documents = filter_documents(
        state,
        user_of(request),
        kinds,
        kind=filters["art"],
        year=year_of(filters["jahr"]),
        issuer=filters["aussteller"],
        query=filters["q"],
        status=filters["zustand"],
    )
    chosen = next((d for d in documents if d.id == selected), None)
    issuers = {i.id: i for i in state.of_kind(Issuer)}
    return render(
        request,
        "documents/list.html",
        status_code,
        documents=documents,
        states={d.id: document_state(state, kinds, d) for d in documents},
        document_states=[s for s in DocumentState if s is not DocumentState.BELEG],
        selected=chosen,
        detail=document_detail(request, chosen, issuer_text, year) if chosen else None,
        issuer_names={i.id: i.name for i in issuers.values()},
        issuer_list=sorted(issuers.values(), key=lambda i: name_key(i.name)),
        kind_titles={k.key: k.title for k in kinds.values()},
        filters=filters,
        base=urlencode({k: v for k, v in filters.items() if v}),
        preview_kind=chosen and preview_kind(chosen.path),
        preview_url=chosen and document_file_url(chosen.id),
        without_kind=WITHOUT_KIND,
        without_issuer=WITHOUT_ISSUER,
        notice=notice,
        existing=existing,
    )
