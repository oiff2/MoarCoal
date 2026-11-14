"""Routen eines Dokuments: Ändern, Löschen, Auslesen, Bestätigen und die Datei (Spec 3.6).

Die Details eines Dokuments stehen im Reiter Dokumente (`document_list.py`); `GET /dokumente/{id}`
leitet dorthin um. Erfolg leitet in den Reiter, Abweisungen zeigen ihn mit den Gründen. Ändern,
Löschen, Auslesen und Bestätigen sind POST und brauchen den Origin (Middleware).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.document_list import documents_page, read_document_choice
from moarcoal.documents import IntakeRejected, change_document
from moarcoal.extraction import Extractor
from moarcoal.links import document_url
from moarcoal.previews import file_response
from moarcoal.proposals import (
    ReadOutRejected,
    confirm,
    document_of,
    proposals_of,
    read_out,
)
from moarcoal.storage import Applied, Delete, Document
from moarcoal.web import document_kinds, form_fields, store_of, user_of

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


def _refused(request: Request, document: Document, status_code: int, *reasons: str) -> HTMLResponse:
    """Der Reiter Dokumente mit dem Dokument und den Gründen der Abweisung."""
    return documents_page(request, status_code, selected=document.id, notice=" ".join(reasons))


def _in_list(document: Document) -> RedirectResponse:
    """Zurück in den Reiter Dokumente, das Dokument gewählt."""
    return RedirectResponse(document_url(document.id), status_code=303)


@router.get("/{document_id}")
def moved(document_id: str) -> RedirectResponse:
    """Die Details stehen im Reiter Dokumente; 308 wie bei den alten Adressen `/eingang…`."""
    return RedirectResponse(document_url(document_id), status_code=308)


@router.get("/{document_id}/datei")
def file(request: Request, document_id: str) -> Response:
    """Die Datei des Dokuments (Vorschau); hat sie sich seit dem Aufnehmen geändert: 404."""
    document = _document(request, document_id)
    return file_response(store_of(request), document.site, document.path, document.sha256)


@router.post("/{document_id}/aendern")
def change(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Aussteller ändern (auch entfernen; neuer Aussteller oder Alias im selben Vorgang), dazu Art
    und Jahr, wenn das Formular sie mitschickt (gesperrte Felder fehlen)."""
    document = _document(request, document_id)
    store = store_of(request)
    kinds = document_kinds(request)
    choice = read_document_choice(store.state(), kinds, fields)
    result = (
        choice
        if isinstance(choice, IntakeRejected)
        else change_document(
            store,
            kinds,
            document,
            choice.issuer.address,
            choice.issuer.changes,
            choice.kind_key,
            choice.year,
        )
    )
    if isinstance(result, IntakeRejected):
        return documents_page(
            request,
            422,
            selected=document.id,
            notice=" ".join(result.reasons),
            existing=result.existing,
            issuer_text=fields.get("issuer_text", ""),
            year=fields.get("year", ""),
        )
    return _in_list(document)


@router.post("/{document_id}/loeschen")
def delete(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Nimmt nur das Dokument weg; die Datei bleibt und ist wieder offen. Verweisen noch Einträge
    darauf, weist `Store.apply` ab."""
    document = _document(request, document_id)
    result = store_of(request).apply([Delete(document.address, fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _refused(request, document, 409, *result.reasons.values())
    return RedirectResponse("/belege/dokumente", status_code=303)


@router.post("/{document_id}/auslesen")
def extract(request: Request, document_id: str) -> Response:
    document = _document(request, document_id)
    extractor: Extractor = request.app.state.extractor
    result = read_out(
        store_of(request), extractor, document_kinds(request), user_of(request), document
    )
    if isinstance(result, ReadOutRejected):
        return _refused(request, document, 409, result.message)
    return _in_list(document)


@router.post("/{document_id}/bestaetigen")
def confirm_fields(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    document = _document(request, document_id)
    proposals = proposals_of(store_of(request).state(), document)
    if not proposals:
        return _refused(request, document, 409, "Zu diesem Dokument gibt es keinen Vorschlag.")
    key = None if fields.get("all") else fields.get("field", "")
    kind = document_kinds(request).get(document.document_kind or "")
    template = None if kind is None else kind.extraction_template
    result = confirm(store_of(request), proposals[-1], template, key, fields.get("correction"))
    if not isinstance(result, Applied):
        return _refused(request, document, 409, result.message)
    return _in_list(document)
