"""Seiten des Moduls Arbeit: erfassen, ändern, löschen. Geschrieben wird nur über `apply`.

Alles steht auf `/arbeit` (`overview.work_page`); die Adresse eines Eintrags leitet dorthin, mit
dem Eintrag aufgeklappt.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import year_of
from moarcoal.modules.work.common import MODULE_KEY, work_url
from moarcoal.modules.work.overview import submitted, work_page
from moarcoal.modules.work.workplace.entries import FirstWorkplace, WorkEquipment
from moarcoal.modules.work.workplace.forms import KINDS, EntryForm, Fields, prefill_from
from moarcoal.registration import ModuleState
from moarcoal.storage import Applied, Change, Delete, Entry, Put, new_id
from moarcoal.web.helpers import (
    chosen_year,
    entry_of,
    form_fields,
    module_state,
    rejection_reasons,
    store_of,
    user_of,
)

router = APIRouter(prefix="/arbeit")


def _kind(slug: str) -> EntryForm:
    kind = KINDS.get(slug)
    if kind is None:
        raise HTTPException(404)
    return kind


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def _year(entry: Entry) -> int:
    assert isinstance(entry, FirstWorkplace | WorkEquipment)
    return entry.year


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return work_page(
        request, chosen_year(request), open_entry=request.query_params.get("eintrag", "")
    )


@router.get("/{slug}/{entry_id}")
def edit_page(request: Request, slug: str, entry_id: str) -> Response:
    """Die frühere Änderungsseite: die Seite Arbeit im Jahr des Eintrags, der Eintrag offen."""
    entry = entry_of(_own_state(request), _kind(slug).model, entry_id)
    return RedirectResponse(f"{work_url(_year(entry))}&eintrag={entry.id}", status_code=303)


def _rejected(
    request: Request,
    year: int,
    kind: EntryForm,
    entry_id: str,
    fields: Fields,
    errors: list[str],
    status: int,
) -> HTMLResponse:
    """Die Seite im Jahr `year`, das abgeschickte Formular offen mit den Gründen."""
    return work_page(request, year, status, sent=submitted(kind, entry_id, fields, errors))


def _input_year(request: Request, fields: Fields) -> int:
    """Das Jahr einer abgewiesenen Eingabe: ihr Feld, sonst das Jahr der Seite."""
    return year_of(fields.get("year", ""), in_range=True) or chosen_year(request)


def _write(
    request: Request, kind: EntryForm, entry_id: str, fields: Fields, change: Change, year: int
) -> Response:
    result = store_of(request).apply([change])
    if not isinstance(result, Applied):
        reasons = rejection_reasons(result)
        return _rejected(request, year, kind, entry_id, fields, reasons, 409)
    return RedirectResponse(work_url(year), status_code=303)


@router.post("/{slug}")
def create(
    request: Request, slug: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    entry, errors = kind.build(fields, user_of(request), new_id())
    if entry is None:
        return _rejected(request, _input_year(request, fields), kind, "", fields, errors, 422)
    return _write(request, kind, "", fields, Put(entry), _year(entry))


@router.post("/{slug}/{entry_id}")
def update(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    year = _year(entry_of(_own_state(request), kind.model, entry_id))
    fields = fields | {"year": str(year)}  # das Steuerjahr eines Eintrags bleibt
    entry, errors = kind.build(fields, user_of(request), entry_id)
    if entry is None:
        return _rejected(request, year, kind, entry_id, fields, errors, 422)
    change = Put(entry, expected=fields.get("checksum", ""))
    return _write(request, kind, entry_id, fields, change, _year(entry))


@router.post("/{slug}/{entry_id}/loeschen")
def delete(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    entry = entry_of(_own_state(request), kind.model, entry_id)
    change = Delete(entry.address, expected=fields.get("checksum", ""))
    shown = prefill_from(entry) | fields  # bei Abweisung zeigt das Formular den Eintrag
    return _write(request, kind, entry_id, shown, change, _year(entry))
