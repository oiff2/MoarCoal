"""Seiten des Moduls Steuerjahr: Übertragungsprotokoll aufnehmen und die Zeilen ansehen."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.documents import DocumentKind, IntakeRejected, take_in
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Document, EntryAddress
from moarcoal.web import form_fields, module_state, render, store_of, user_of

MODULE_KEY = "tax_year"
router = APIRouter(prefix="/steuerjahr")

type Fields = dict[str, str]
DEFAULT_YEAR = "2025"


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def _document_kinds(request: Request) -> dict[str, DocumentKind]:
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    return {k.key: k for r in registrations for k in r.document_kinds}


def _overview(
    request: Request, errors: list[str], values: Fields, status_code: int = 200
) -> HTMLResponse:
    state = _own_state(request)
    documents = {d.address: d for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [
        (reading, documents.get(reading.document))
        for reading in sorted(state.all(ProtocolReading), key=lambda r: (r.year, r.id))
    ]
    return render(
        request,
        "tax_year/index.html",
        status_code,
        readings=readings,
        sites=store_of(request).site_names(),
        errors=errors,
        values=values,
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request, [], {"year": DEFAULT_YEAR})


@router.post("/uebertragungsprotokolle")
def take_in_protocol(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    try:
        year = int(fields.get("year", "").strip())
    except ValueError:
        return _overview(request, ["Steuerjahr: ganze Zahl, z. B. 2025"], fields, 422)
    result = take_in(
        store_of(request),
        _document_kinds(request),
        user_of(request),
        fields.get("site", ""),
        fields.get("path", "").strip(),
        TRANSFER_PROTOCOL_KEY,
        year,
    )
    if isinstance(result, IntakeRejected):
        return _overview(request, list(result.reasons), fields, 422)
    (reading,) = result.entries
    return RedirectResponse(f"/steuerjahr/uebertragungsprotokolle/{reading.id}", status_code=303)


@router.get("/uebertragungsprotokolle/{reading_id}", response_class=HTMLResponse)
def protocol_page(request: Request, reading_id: str) -> HTMLResponse:
    try:
        address = EntryAddress(kind=ProtocolReading.__name__, id=reading_id)
    except ValueError as error:
        raise HTTPException(404) from error
    state = _own_state(request)
    reading = state.get(address)
    if not isinstance(reading, ProtocolReading):
        raise HTTPException(404)
    document: Document | None = next(
        (d for d in state.documents() if d.address == reading.document), None
    )
    return render(request, "tax_year/protocol.html", reading=reading, document=document)
