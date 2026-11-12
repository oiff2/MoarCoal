"""Seiten des Moduls Steuerjahr: Übersicht, Protokollzeilen ansehen, Anlage N."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from moarcoal.modules.tax_year.anlage_n import FORMS
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.registration import ModuleState
from moarcoal.storage import Document, EntryAddress
from moarcoal.values.model import Period
from moarcoal.web import module_state, render, user_of, values_of

MODULE_KEY = "tax_year"
router = APIRouter(prefix="/steuerjahr")


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def _overview(request: Request) -> HTMLResponse:
    state = _own_state(request)
    documents = {d.address: d for d in state.documents(TRANSFER_PROTOCOL_KEY)}
    readings = [
        (reading, documents.get(reading.document))
        for reading in sorted(state.all(ProtocolReading), key=lambda r: (r.year, r.id))
    ]
    return render(
        request,
        "tax_year/index.html",
        readings=readings,
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request)


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


@router.get("/anlage-n/{year}", response_class=HTMLResponse)
def anlage_n(request: Request, year: int) -> HTMLResponse:
    fields = FORMS.get(year)
    if fields is None:
        raise HTTPException(404)
    values = values_of(request)
    user = user_of(request)
    rows = [(field, values.get(field.key, user, Period.year(year))) for field in fields]
    return render(
        request,
        "tax_year/anlage_n.html",
        year=year,
        rows=rows,
        findings=values.finding_list(user, year),  # Vorlage zeigt die sichtbaren Befunde
    )


def entry_url(address: EntryAddress) -> str | None:
    """Link zur Seite eines eingelesenen Protokolls, sonst `None`."""
    if address.kind == ProtocolReading.__name__:
        return f"/steuerjahr/uebertragungsprotokolle/{address.id}"
    return None
