"""Seiten des Moduls Steuerjahr: Übersicht der Anlagen, Protokollzeilen, Seiten je Anlage."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from moarcoal.modules.tax_year.anlagen import Anlage, YearAnlage, protocol_contents, year_anlagen
from moarcoal.modules.tax_year.assessment_check import current_assessment
from moarcoal.modules.tax_year.entries import MODULE_KEY, TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.inputs import changes_for_input, current_input, typed_field
from moarcoal.modules.tax_year.links import protocol_url
from moarcoal.modules.tax_year.protocol_check import latest_reading
from moarcoal.modules.tax_year.snapshot_check import describe_frozen, latest_snapshot
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Document, EntryAddress
from moarcoal.values.model import Period
from moarcoal.web.helpers import (
    entry_of,
    finding_list_of,
    form_fields,
    global_year,
    module_state,
    rejection_text,
    render,
    store_of,
    user_of,
    values_of,
)


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def router_for(anlagen: Sequence[Anlage]) -> APIRouter:
    """Die Seiten des Steuerjahrs über den angemeldeten `anlagen`; jede Anlage hat dieselben
    Seiten, ihr Katalog und ihre Struktur machen den Unterschied."""
    router = APIRouter(prefix="/steuerjahr")

    def year_anlage(request: Request, form: str, year: int) -> YearAnlage:
        reading = latest_reading(_own_state(request), year)
        found = next((a for a in year_anlagen(anlagen, year, reading) if a.slug == form), None)
        if found is None:
            raise HTTPException(404)
        return found

    @router.get("", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        state = _own_state(request)
        year = global_year(request)
        documents = {d.address: d for d in state.documents(TRANSFER_PROTOCOL_KEY)}
        readings = [
            (reading, documents.get(reading.document))
            for reading in sorted(state.all(ProtocolReading), key=lambda r: (r.year, r.id))
        ]
        return render(
            request,
            "tax_year/index.html",
            year=year,
            anlagen=year_anlagen(anlagen, year, latest_reading(state, year)),
            readings=readings,
        )

    @router.get("/uebertragungsprotokolle/{reading_id}", response_class=HTMLResponse)
    def protocol_page(request: Request, reading_id: str) -> HTMLResponse:
        state = _own_state(request)
        reading = entry_of(state, ProtocolReading, reading_id)
        document: Document | None = next(
            (d for d in state.documents() if d.address == reading.document), None
        )
        return render(request, "tax_year/protocol.html", reading=reading, document=document)

    @router.get("/anlage-{form}/{year}", response_class=HTMLResponse)
    def anlage(request: Request, form: str, year: int) -> HTMLResponse:
        """Die erste Seite der Anlage; die Befunde verweisen auf diese Adresse."""
        return _anlage_page(request, year_anlage(request, form, year), None)

    @router.get("/anlage-{form}/{year}/{slug}", response_class=HTMLResponse)
    def anlage_page(request: Request, form: str, year: int, slug: str) -> HTMLResponse:
        return _anlage_page(request, year_anlage(request, form, year), slug)

    def _anlage_page(request: Request, anlage: YearAnlage, slug: str | None) -> HTMLResponse:
        year = anlage.year
        page = next((p for p in anlage.pages if slug is None or p.slug == slug), None)
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
        reading = latest_reading(state, year)
        snapshot = latest_snapshot(state, year)
        assessment = current_assessment(state, year, anlage.fields)
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
            "tax_year/anlage.html",
            year=year,
            anlage=anlage,
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
            transferred=protocol_contents(reading, anlage.form) if anlage.provisional else None,
            findings=finding_list_of(request, year),  # Vorlage zeigt die sichtbaren Befunde
        )

    @router.post("/anlage-{form}/{year}/eingabe/{elster_id}", response_class=HTMLResponse)
    def save_input(
        request: Request,
        form: str,
        year: int,
        elster_id: str,
        fields: Annotated[dict[str, str], Depends(form_fields)],
    ) -> HTMLResponse:
        """Legt die Eingabe zu einem Eintippfeld ab und liefert das Feld neu (htmx-Teilantwort).

        Auch eine abgelehnte Eingabe antwortet mit 200, denn htmx tauscht Fehlerantworten nicht
        ein.
        """
        mine = [a for a in anlagen if a.slug == form]
        field = typed_field(mine, year, elster_id)
        if field is None:
            raise HTTPException(404)
        text = fields.get("content", "")
        changes, error = changes_for_input(_own_state(request), year, field, text)
        if error is None and changes:
            result = store_of(request).apply(changes)
            if not isinstance(result, Applied):
                error = rejection_text(result)
        return _input_part(request, form, year, field, error, text if error else None)

    return router


def _input_part(
    request: Request,
    form: str,
    year: int,
    field: FormField,
    error: str | None,
    typed: str | None,
) -> HTMLResponse:
    entry = current_input(_own_state(request), year, field)
    content = typed if typed is not None else entry.content if entry else None
    return render(
        request,
        "tax_year/_eingabe_teil.html",
        year=year,
        form_slug=form,
        field=field,
        content=content,
        error=error,
    )


def entry_url(address: EntryAddress) -> str | None:
    """Link zur Seite eines eingelesenen Protokolls, sonst `None`."""
    if address.kind == ProtocolReading.__name__:
        return protocol_url(address.id)
    return None
