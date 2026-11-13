"""Seite eines Dokuments: Auslesen auf Knopfdruck und Bestätigungsansicht des Vorschlags (Spec 3.6).

GET schreibt nie; Auslesen und Bestätigen sind POST und brauchen den Origin (Middleware).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.document_list import REFERENCE_LABELS
from moarcoal.documents import DocumentKind, IntakeRejected, change_document, references_to
from moarcoal.extraction import Extractor
from moarcoal.issuer_field import resolve_issuer
from moarcoal.previews import file_response
from moarcoal.proposals import (
    ReadOutRejected,
    confirm,
    document_of,
    proposals_of,
    read_out,
)
from moarcoal.storage import Applied, Delete, Document, entry_checksum
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
    year: str = "",
    existing: Document | None = None,
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
        year=year,
        kinds=list(document_kinds(request).values()),
        references=references_to(state, document),
        checksum=entry_checksum(document),
        labels=REFERENCE_LABELS,
        default_year=DEFAULT_YEAR,
        kind=kind,
        template=template,
        proposal=proposal,
        notice=notice,
        existing=existing,
    )


@router.get("/{document_id}", response_class=HTMLResponse)
def show(request: Request, document_id: str) -> HTMLResponse:
    return _page(request, _document(request, document_id))


@router.get("/{document_id}/datei")
def file(request: Request, document_id: str) -> Response:
    """Die Datei des Dokuments (Vorschau); hat sie sich seit dem Aufnehmen geändert: 404."""
    document = _document(request, document_id)
    return file_response(store_of(request), document.site, document.path, document.sha256)


def _back(document_id: str, fields: Fields) -> str:
    """Wohin nach dem Ändern: zurück in die Liste, wenn das Formular von dort kam."""
    if fields.get("from") == "liste":
        return f"/belege/dokumente?dokument={document_id}"
    return f"/dokumente/{document_id}"


@router.post("/{document_id}/aendern")
def change(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Aussteller ändern (auch entfernen; neuer Aussteller oder Alias im selben Vorgang), dazu Art
    und Jahr, wenn das Formular sie mitschickt (gesperrte Felder fehlen)."""
    document = _document(request, document_id)
    store = store_of(request)
    kinds = document_kinds(request)
    chosen = resolve_issuer(store.state(), fields)

    def rejected(*reasons: str, existing: Document | None = None) -> Response:
        return _page(
            request,
            document,
            422,
            " ".join(reasons),
            fields.get("issuer_text", ""),
            fields.get("year", ""),
            existing,
        )

    if isinstance(chosen, str):
        return rejected(chosen)
    kind_key = fields.get("kind")
    year = None
    if kind_key is not None and (kind := kinds.get(kind_key)) is not None and kind.has_period:
        try:
            year = int(fields.get("year", "").strip())
        except ValueError:
            return rejected("Steuerjahr: ganze Zahl, z. B. 2025")
    result = change_document(store, kinds, document, chosen.address, chosen.changes, kind_key, year)
    if isinstance(result, IntakeRejected):
        return rejected(*result.reasons, existing=result.existing)
    return RedirectResponse(_back(document.id, fields), status_code=303)


@router.post("/{document_id}/loeschen")
def delete(
    request: Request, document_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Nimmt nur das Dokument weg; die Datei bleibt und ist wieder offen. Verweisen noch Einträge
    darauf, weist `Store.apply` ab."""
    document = _document(request, document_id)
    result = store_of(request).apply([Delete(document.address, fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _page(request, document, 409, " ".join(result.reasons.values()))
    return RedirectResponse("/belege/dokumente", status_code=303)


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
