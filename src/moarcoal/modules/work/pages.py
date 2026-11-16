"""Seiten des Moduls Arbeit: erfassen, ändern, löschen. Geschrieben wird nur über `apply`."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.modules.work.common import MODULE_KEY
from moarcoal.modules.work.trips.view import chosen_year, trips_context
from moarcoal.modules.work.workplace.entries import FirstWorkplace, WorkEquipment
from moarcoal.modules.work.workplace.forms import (
    KINDS,
    EntryForm,
    Fields,
    prefill_from,
    prefill_new,
)
from moarcoal.modules.work.workplace.values import DISTANCE_KM, EQUIPMENT, WORKDAYS
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Applied,
    Delete,
    Put,
    entry_checksum,
    new_id,
)
from moarcoal.values.model import Period
from moarcoal.web.helpers import (
    entry_of,
    form_fields,
    module_state,
    rejection_reasons,
    render,
    store_of,
    user_of,
    values_of,
)

router = APIRouter(prefix="/arbeit")


def _kind(slug: str) -> EntryForm:
    kind = KINDS.get(slug)
    if kind is None:
        raise HTTPException(404)
    return kind


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def _years(request: Request, state: ModuleState) -> list[dict[str, Any]]:
    """Je Jahr mit Angaben die Ausgewiesenen Werte des Moduls, zum Anzeigen."""
    entries = [*state.all(FirstWorkplace), *state.all(WorkEquipment)]
    years = sorted({e.year for e in entries})
    values = values_of(request)
    user = user_of(request)
    result: list[dict[str, Any]] = []
    for year in years:
        period = Period.year(year)
        result.append(
            {
                "year": year,
                "workplaces": list(
                    zip(
                        [e for e in state.all(FirstWorkplace) if e.year == year],
                        values.all(WORKDAYS, user, period),
                        values.all(DISTANCE_KM, user, period),
                        strict=True,
                    )
                ),
                "equipment": values.get(EQUIPMENT, user, period),
            }
        )
    return result


def _prefill_all(submitted: str | None = None, fields: Fields | None = None) -> dict[str, Fields]:
    """Vorbelegung der Formulare der Übersicht: Eingabe für die abgeschickte Art, sonst neu."""
    return {s: fields if s == submitted and fields is not None else prefill_new(s) for s in KINDS}


def _overview(
    request: Request,
    errors: dict[str, list[str]],
    values: dict[str, Fields],
    status_code: int = 200,
) -> HTMLResponse:
    state = _own_state(request)
    return render(
        request,
        "work/index.html",
        status_code,
        years=_years(request, state),
        workplaces=[(e, entry_checksum(e)) for e in state.all(FirstWorkplace)],
        equipment=[(e, entry_checksum(e)) for e in state.all(WorkEquipment)],
        kinds=KINDS,
        errors=errors,
        values=values,
        **trips_context(request, chosen_year(request)),
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request, {}, _prefill_all())


@router.get("/{slug}/{entry_id}", response_class=HTMLResponse)
def edit_page(request: Request, slug: str, entry_id: str) -> HTMLResponse:
    kind = _kind(slug)
    entry = entry_of(_own_state(request), kind.model, entry_id)
    return render(
        request,
        "work/edit.html",
        kind=kind,
        entry=entry,
        values=prefill_from(entry),
        checksum=entry_checksum(entry),
        errors=[],
    )


def _edit_response(
    request: Request, kind: EntryForm, entry_id: str, fields: Fields, errors: list[str], status: int
) -> HTMLResponse:
    return render(
        request,
        "work/edit.html",
        status,
        kind=kind,
        entry=None,
        entry_id=entry_id,
        values=fields,
        checksum=fields.get("checksum", ""),
        errors=errors,
    )


@router.post("/{slug}")
def create(
    request: Request, slug: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    entry, errors = kind.build(fields, user_of(request), new_id())
    if entry is None:
        return _overview(
            request,
            {slug: errors},
            _prefill_all(slug, fields),
            422,
        )
    result = store_of(request).apply([Put(entry)])
    if not isinstance(result, Applied):
        reasons = rejection_reasons(result)
        return _overview(
            request,
            {slug: reasons},
            _prefill_all(slug, fields),
            409,
        )
    return RedirectResponse("/arbeit", status_code=303)


@router.post("/{slug}/{entry_id}")
def update(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    entry_of(_own_state(request), kind.model, entry_id)
    entry, errors = kind.build(fields, user_of(request), entry_id)
    if entry is None:
        return _edit_response(request, kind, entry_id, fields, errors, 422)
    result = store_of(request).apply([Put(entry, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        reasons = rejection_reasons(result)
        return _edit_response(request, kind, entry_id, fields, reasons, 409)
    return RedirectResponse("/arbeit", status_code=303)


@router.post("/{slug}/{entry_id}/loeschen")
def delete(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    entry = entry_of(_own_state(request), kind.model, entry_id)
    result = store_of(request).apply([Delete(entry.address, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        reasons = rejection_reasons(result)
        return _edit_response(request, kind, entry_id, fields, reasons, 409)
    return RedirectResponse("/arbeit", status_code=303)
