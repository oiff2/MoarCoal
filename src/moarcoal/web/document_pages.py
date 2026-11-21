"""Routen eines Dokuments: Ändern, Löschen, Auslesen, Bestätigen und die Datei (Spec 3.6).

Die Details eines Dokuments stehen im Reiter Dokumente (`document_list.py`); `GET /dokumente/{id}`
leitet dorthin um. Erfolg leitet in den Reiter, Abweisungen zeigen ihn mit den Gründen. Ändern,
Löschen, Auslesen und Bestätigen sind POST und brauchen den Origin (Middleware).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.documents import IntakeRejected, change_document, read_document_choice
from moarcoal.extraction import Extractor
from moarcoal.proposals import (
    ReadOutRejected,
    confirm,
    latest_proposal,
    read_out,
    template_of,
)
from moarcoal.storage import Applied, Delete, Document
from moarcoal.web.document_list import documents_page
from moarcoal.web.helpers import (
    document_kinds,
    entry_of,
    form_fields,
    rejection_text,
    store_of,
    user_of,
)
from moarcoal.web.links import document_url
from moarcoal.web.previews import file_response

router = APIRouter(prefix="/dokumente")

type Fields = dict[str, str]


def _document(request: Request, document_id: str) -> Document:
    return entry_of(store_of(request).state(), Document, document_id, user_of(request))


def _refused(request: Request, document: Document, status_code: int, notice: str) -> HTMLResponse:
    """Der Reiter Dokumente mit dem Dokument und dem Hinweis zur Abweisung."""
    return documents_page(request, status_code, selected=document.id, notice=notice)


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
    """Aussteller und Bezeichnung ändern (auch entfernen; neuer Aussteller oder Alias im selben
    Vorgang), dazu Art und Jahr, wenn das Formular sie mitschickt (gesperrte Felder fehlen)."""
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
            label=choice.label,
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
        return _refused(request, document, 409, rejection_text(result))
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
    proposal = latest_proposal(store_of(request).state(), document)
    if proposal is None:
        return _refused(request, document, 409, "Zu diesem Dokument gibt es keinen Vorschlag.")
    key = None if fields.get("all") else fields.get("field", "")
    template = template_of(document_kinds(request), document)
    result = confirm(store_of(request), proposal, template, key, fields.get("correction"))
    if not isinstance(result, Applied):
        return _refused(request, document, 409, result.message)
    return _in_list(document)
