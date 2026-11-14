"""Seiten des Moduls Steuerjahr: Übersicht, Protokollzeilen ansehen, Anlage N."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES
from moarcoal.modules.tax_year.comparison import (
    current_assessment,
    describe_frozen,
    latest_snapshot,
)
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.modules.tax_year.structure import form_pages
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
    """Die erste Seite der Anlage N; die Befunde verweisen auf diese Adresse."""
    return _anlage_n_page(request, year, None)


@router.get("/anlage-n/{year}/{slug}", response_class=HTMLResponse)
def anlage_n_page(request: Request, year: int, slug: str) -> HTMLResponse:
    return _anlage_n_page(request, year, slug)


def _anlage_n_page(request: Request, year: int, slug: str | None) -> HTMLResponse:
    fields = FORMS.get(year)
    if fields is None:
        raise HTTPException(404)
    pages = form_pages(STRUCTURES[year], fields)
    page = next((p for p in pages if slug is None or p.slug == slug), None)
    if page is None:
        raise HTTPException(404)
    values = values_of(request)
    user = user_of(request)
    state = _own_state(request)
    rows = [
        (
            row,
            values.get(row.field.key, user, Period.year(year)) if row.field.computed else None,
        )
        for row in page.rows
    ]
    snapshot = latest_snapshot(state, year)
    assessment = current_assessment(state, year, fields)
    printed = {} if assessment is None else assessment[1]
    frozen = {}
    if snapshot is not None:
        frozen = {
            v.ref.key: describe_frozen(row.field, v)
            for row in page.rows
            for v in snapshot.values
            if v.requested and v.ref.key == row.field.key
        }
    return render(
        request,
        "tax_year/anlage_n.html",
        year=year,
        pages=pages,
        page=page,
        rows=rows,
        snapshot=snapshot,
        frozen=frozen,
        printed=printed,
        findings=values.finding_list(user, year),  # Vorlage zeigt die sichtbaren Befunde
    )


def entry_url(address: EntryAddress) -> str | None:
    """Link zur Seite eines eingelesenen Protokolls, sonst `None`."""
    if address.kind == ProtocolReading.__name__:
        return f"/steuerjahr/uebertragungsprotokolle/{address.id}"
    return None
