"""Seiten des Moduls Steuerjahr: Übersicht der Anlagen, Protokollzeilen, Seiten je Anlage."""

from collections.abc import Iterable, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import year_of
from moarcoal.modules.tax_year.anlage_view import AnlageGrading, anlage_view, grade_anlage
from moarcoal.modules.tax_year.anlagen import Anlage, YearAnlage, year_anlagen
from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment
from moarcoal.modules.tax_year.church_tax_pages import add_routes
from moarcoal.modules.tax_year.church_tax_view import PaymentForm
from moarcoal.modules.tax_year.entries import (
    MODULE_KEY,
    TRANSFER_PROTOCOL_KEY,
    ProtocolReading,
    current_person_input,
)
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.modules.tax_year.inputs import changes_for_input, current_input, typed_field
from moarcoal.modules.tax_year.links import protocol_url
from moarcoal.modules.tax_year.person_input import (
    in_this_return_choices,
    year_person_input_changes,
)
from moarcoal.modules.tax_year.protocol_check import latest_reading
from moarcoal.modules.tax_year.special_parts import PageParams
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Document, EntryAddress
from moarcoal.values.model import ValueRef
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


def _tree(request: Request, year: int, listed: Sequence[YearAnlage]) -> dict[str, AnlageGrading]:
    """Die Stufe je Anlage für die Punkte im Baum, nach Adressteil der Anlage."""
    found = finding_list_of(request, year)
    findings = [*found.visible, *(h.finding for h in found.hidden)]
    return {
        a.slug: grade_anlage(_own_state(request), values_of(request), findings, a) for a in listed
    }


def router_for(anlagen: Sequence[Anlage]) -> APIRouter:
    """Die Seiten des Steuerjahrs über den angemeldeten `anlagen`; jede Anlage hat dieselben
    Seiten, ihr Katalog und ihre Struktur machen den Unterschied."""
    router = APIRouter(prefix="/steuerjahr")

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
            "note": (saved and saved.note) or "",
        }
        listed = year_anlagen(anlagen, year, latest_reading(state, year))
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
            anlagen=listed,
            tree=_tree(request, year, listed),
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
        """Legt die Eingaben zur Person im Jahr ab (Beruf, Telefon, Auswahl, Bearbeitungsnotiz)."""
        if year_of(str(year), in_range=True) is None:
            raise HTTPException(404)
        changes = year_person_input_changes(
            _own_state(request),
            year,
            fields.get("occupation", ""),
            fields.get("phone", ""),
            fields.get("in_return", ""),
            fields.get("note", ""),
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
        return _anlage_page(request, year, form, None)

    @router.get("/anlage-{form}/{year}/{slug}", response_class=HTMLResponse)
    def anlage_page(request: Request, form: str, year: int, slug: str) -> HTMLResponse:
        return _anlage_page(request, year, form, slug)

    def _anlage_page(
        request: Request,
        year: int,
        form: str,
        slug: str | None,
        status: int = 200,
        sent: PaymentForm | None = None,
    ) -> HTMLResponse:
        listed = year_anlagen(anlagen, year, latest_reading(_own_state(request), year))
        anlage = next((a for a in listed if a.slug == form), None)
        if anlage is None:
            raise HTTPException(404)
        found = finding_list_of(request, year)
        store_state = store_of(request).state()
        modules = request.app.state.modules
        user = user_of(request)

        def captures(refs: Iterable[ValueRef]) -> list[tuple[str, str]]:
            return capture_links(modules, store_state, user, refs)

        view = anlage_view(
            _own_state(request),
            values_of(request),
            [*found.visible, *(h.finding for h in found.hidden)],
            captures,
            anlage,
            slug,
            PageParams(request.query_params.get("eintrag", ""), sent),
        )
        if view is None:
            raise HTTPException(404)
        return render(
            request,
            "tax_year/anlage.html",
            status,
            year=year,
            anlage=anlage,
            page=view.page,
            view=view,
            anlagen=listed,
            tree=_tree(request, year, listed),
        )

    def sa_page(request: Request, year: int, status: int, sent: PaymentForm | None) -> HTMLResponse:
        return _anlage_page(request, year, "sa", None, status, sent)

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
        typed=field.kind,
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
