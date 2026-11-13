"""Seite eines Dokuments: Auslesen auf Knopfdruck und Bestätigungsansicht des Vorschlags (Spec 3.6).

GET schreibt nie; Auslesen und Bestätigen sind POST und brauchen den Origin (Middleware).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.documents import DocumentKind
from moarcoal.extraction import Extractor
from moarcoal.issuer_field import resolve_issuer
from moarcoal.proposals import (
    ReadOutRejected,
    confirm,
    document_of,
    proposals_of,
    read_out,
)
from moarcoal.storage import Applied, Document, Put, entry_checksum
from moarcoal.web import document_kinds, form_fields, render, store_of, user_of

router = APIRouter(prefix="/dokumente")

type Fields = dict[str, str]


def _document(request: Request, document_id: str) -> Document:
    try:
        document = document_of(store_of(request).state(), user_of(request), document_id)
    except ValidationError:
        document = None
    if document is None:
        raise HTTPException(404)
    return document


def _kind(request: Request, document: Document) -> DocumentKind | None:
    return document_kinds(request).get(document.document_kind or "")


def _page(
    request: Request,
    document: Document,
    status_code: int = 200,
    notice: str = "",
    issuer_text: str = "",
) -> HTMLResponse:
    kind = _kind(request, document)
    template = None if kind is None else kind.extraction_template
    state = store_of(request).state()
    proposals = proposals_of(state, document)
    proposal = proposals[-1] if proposals else None
    issuer = state.get(document.issuer) if document.issuer else None
    return render(
        request,
        "documents/show.html",
        status_code,
        document=document,
        issuer=issuer,
        issuer_text=issuer_text,
        kind=kind,
        template=template,
        proposal=proposal,
        notice=notice,
    )


@router.get("/{document_id}", response_class=HTMLResponse)
def show(request: Request, document_id: str) -> HTMLResponse:
    return _page(request, _document(request, document_id))


@router.post("/{document_id}/aussteller")
def change_issuer(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Aussteller ändern (auch entfernen); neuer Aussteller oder Alias im selben Vorgang."""
    document = _document(request, document_id)
    store = store_of(request)
    chosen = resolve_issuer(store.state(), fields)
    if isinstance(chosen, str):
        return _page(request, document, 422, chosen, fields.get("issuer_text", ""))
    changed = document.model_copy(update={"issuer": chosen.address})
    result = store.apply([*chosen.changes, Put(changed, entry_checksum(document))])
    if not isinstance(result, Applied):
        return _page(request, document, 409, " ".join(result.reasons.values()))
    return RedirectResponse(f"/dokumente/{document.id}", status_code=303)


@router.post("/{document_id}/auslesen")
def extract(request: Request, document_id: str) -> Response:
    document = _document(request, document_id)
    extractor: Extractor = request.app.state.extractor
    result = read_out(
        store_of(request), extractor, document_kinds(request), user_of(request), document
    )
    if isinstance(result, ReadOutRejected):
        return _page(request, document, 409, result.message)
    return RedirectResponse(f"/dokumente/{document.id}", status_code=303)


@router.post("/{document_id}/bestaetigen")
def confirm_fields(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    document = _document(request, document_id)
    proposals = proposals_of(store_of(request).state(), document)
    if not proposals:
        return _page(request, document, 409, "Zu diesem Dokument gibt es keinen Vorschlag.")
    key = None if fields.get("all") else fields.get("field", "")
    kind = _kind(request, document)
    template = None if kind is None else kind.extraction_template
    result = confirm(store_of(request), proposals[-1], template, key, fields.get("correction"))
    if not isinstance(result, Applied):
        return _page(request, document, 409, result.message)
    return RedirectResponse(f"/dokumente/{document.id}", status_code=303)
