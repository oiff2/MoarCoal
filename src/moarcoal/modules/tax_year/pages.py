"""Seiten des Moduls Steuerjahr: Übersicht der Anlagen, Protokollzeilen, Seiten je Anlage."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import year_of
from moarcoal.modules.tax_year.anlagen import Anlage, YearAnlage, protocol_contents, year_anlagen
from moarcoal.modules.tax_year.assessment_check import current_assessment
from moarcoal.modules.tax_year.capture import foreign_refs
from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment
from moarcoal.modules.tax_year.church_tax_pages import (
    PaymentForm,
    add_routes,
    church_view,
)
from moarcoal.modules.tax_year.entries import MODULE_KEY, TRANSFER_PROTOCOL_KEY, ProtocolReading
from moarcoal.modules.tax_year.field_checks import field_checks
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.inputs import changes_for_input, current_input, typed_field
from moarcoal.modules.tax_year.links import protocol_url
from moarcoal.modules.tax_year.person_input import (
    current_person_input,
    field_reasons,
    field_texts,
    in_this_return_choices,
    year_person_input_changes,
)
from moarcoal.modules.tax_year.protocol_check import latest_reading
from moarcoal.modules.tax_year.snapshot_check import describe_frozen, latest_snapshot
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Document, EntryAddress
from moarcoal.values.model import Period
from moarcoal.web.helpers import (
    capture_links,
    entry_of,
    finding_list_of,
    form_fields,
    global_year,
    module_state,
    rejection_reasons,
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
        return _overview(request, global_year(request), None, None, 200)

    def _overview(
        request: Request,
        year: int,
        typed: dict[str, str] | None,
        errors: list[str] | None,
        status: int,
    ) -> HTMLResponse:
        state = _own_state(request)
        saved = current_person_input(state, year)
        person = typed or {
            "occupation": (saved and saved.occupation) or "",
            "phone": (saved and saved.phone) or "",
            "in_return": (saved and saved.in_this_return) or "",
        }
        documents = {d.address: d for d in state.documents(TRANSFER_PROTOCOL_KEY)}
        readings = [
            (reading, documents.get(reading.document))
            for reading in sorted(state.all(ProtocolReading), key=lambda r: (r.year, r.id))
        ]
        return render(
            request,
            "tax_year/index.html",
            status,
            year=year,
            anlagen=year_anlagen(anlagen, year, latest_reading(state, year)),
            anlage=None,
            readings=readings,
            person=person,
            in_return_choices=in_this_return_choices(anlagen, year),
            person_errors=errors or [],
        )

    @router.post("/person/{year}")
    def save_person(
        request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
    ) -> Response:
        """Legt die Eingaben zur Person im Jahr ab (Beruf, Telefon, „In dieser Steuererklärung“)."""
        if year_of(str(year), in_range=True) is None:
            raise HTTPException(404)
        changes = year_person_input_changes(
            _own_state(request),
            year,
            fields.get("occupation", ""),
            fields.get("phone", ""),
            fields.get("in_return", ""),
        )
        result = store_of(request).apply(changes) if changes else None
        if result is not None and not isinstance(result, Applied):
            return _overview(request, year, fields, rejection_reasons(result), 422)
        return RedirectResponse("/steuerjahr", status_code=303)

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

    def _anlage_page(
        request: Request,
        anlage: YearAnlage,
        slug: str | None,
        status: int = 200,
        sent: PaymentForm | None = None,
    ) -> HTMLResponse:
        year = anlage.year
        page = next((p for p in anlage.pages if slug is None or p.slug == slug), None)
        if page is None:
            raise HTTPException(404)
        values = values_of(request)
        user = user_of(request)
        state = _own_state(request)
        reading = latest_reading(state, year)
        snapshot = latest_snapshot(state, year)
        assessment = current_assessment(state, year, anlage.fields)
        printed = {} if assessment is None else assessment[1]
        frozen: dict[str, str] | None = None
        if snapshot is not None:
            frozen = {
                v.ref.key: describe_frozen(row.field, v)
                for row in page.rows
                for v in snapshot.values
                if v.requested and v.ref.key == row.field.key
            }
        transferred = None if reading is None else protocol_contents(reading, anlage.structure)
        texts = field_texts(state, anlage.fields, year)
        reasons = field_reasons(state, anlage.fields, year)
        found = finding_list_of(request, year)
        findings = [*found.visible, *(h.finding for h in found.hidden)]
        rows = [
            (
                row,
                values.get(row.field.key, user, Period.year(year)) if row.field.computed else None,
                field_checks(
                    row.field,
                    transferred=transferred,
                    frozen=frozen,
                    printed=printed,
                    findings=findings,
                    content=texts.get(row.field.elster_id or ""),
                ),
            )
            for row in page.rows
        ]
        modules = request.app.state.modules
        captures = {
            row.field.key: capture_links(
                modules, store_of(request).state(), user, foreign_refs(result)
            )
            for row, result, _ in rows
            if result is not None
        }
        church = (
            church_view(state, year, request.query_params.get("eintrag", ""), sent)
            if anlage.form == "SA"
            else None
        )
        return render(
            request,
            "tax_year/anlage.html",
            status,
            church=church,
            year=year,
            anlage=anlage,
            page=page,
            rows=rows,
            captures=captures,
            texts=texts,
            reasons=reasons,
            snapshot=snapshot,
            inputs={
                row.field.elster_id: entry.content
                for row in page.rows
                if row.field.typed and (entry := current_input(state, year, row.field))
            },
            anlagen=year_anlagen(anlagen, year, reading),
        )

    def sa_page(request: Request, year: int, status: int, sent: PaymentForm | None) -> HTMLResponse:
        return _anlage_page(request, year_anlage(request, "sa", year), None, status, sent)

    add_routes(router, sa_page)

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
    """Link zur Seite eines Protokolls oder einer Kirchensteuerzahlung, sonst `None`."""
    if address.kind == ProtocolReading.__name__:
        return protocol_url(address.id)
    if address.kind == ChurchTaxPayment.__name__:
        return f"/steuerjahr/kirchensteuer/{address.id}"
    return None
