"""Seiten des Moduls Steuerjahr: Übersicht, Protokollzeilen ansehen, Anlage N."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES
from moarcoal.modules.tax_year.comparison import (
    current_assessment,
    describe_frozen,
    latest_snapshot,
)
from moarcoal.modules.tax_year.entries import TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.inputs import changes_for_input, current_input
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Document, EntryAddress
from moarcoal.values.model import Period
from moarcoal.web import form_fields, module_state, render, store_of, user_of, values_of

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
        inputs={
            row.field.elster_id: entry.content
            for row in page.rows
            if row.field.typed and (entry := current_input(state, year, row.field))
        },
        printed=printed,
        findings=values.finding_list(user, year),  # Vorlage zeigt die sichtbaren Befunde
    )


@router.post("/anlage-n/{year}/eingabe/{elster_id}", response_class=HTMLResponse)
def save_input(
    request: Request,
    year: int,
    elster_id: str,
    fields: Annotated[dict[str, str], Depends(form_fields)],
) -> HTMLResponse:
    """Legt die Eingabe zu einem Eintippfeld ab und liefert das Feld neu (htmx-Teilantwort).

    Auch eine abgelehnte Eingabe antwortet mit 200, denn htmx tauscht Fehlerantworten nicht ein.
    """
    field = next((f for f in FORMS.get(year, ()) if f.elster_id == elster_id and f.typed), None)
    if field is None:
        raise HTTPException(404)
    text = fields.get("content", "")
    changes, error = changes_for_input(_own_state(request), year, field, text)
    if error is None and changes:
        result = store_of(request).apply(changes)
        if not isinstance(result, Applied):
            error = " ".join(result.reasons.values())
    return _input_part(request, year, field, error, text if error else None)


def _input_part(
    request: Request, year: int, field: FormField, error: str | None, typed: str | None
) -> HTMLResponse:
    entry = current_input(_own_state(request), year, field)
    content = typed if typed is not None else entry.content if entry else None
    result = (
        values_of(request).get(field.key, user_of(request), Period.year(year))
        if field.computed
        else None
    )
    return render(
        request,
        "tax_year/_eingabe_teil.html",
        year=year,
        field=field,
        result=result,
        content=content,
        error=error,
    )


def entry_url(address: EntryAddress) -> str | None:
    """Link zur Seite eines eingelesenen Protokolls, sonst `None`."""
    if address.kind == ProtocolReading.__name__:
        return f"/steuerjahr/uebertragungsprotokolle/{address.id}"
    return None
