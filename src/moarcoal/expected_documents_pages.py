"""Seite „Erwartete Belege“: Stand je Jahr, anlegen, ändern, löschen (Baustein der Datenebene)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import DocumentKind
from moarcoal.expected_documents import statuses
from moarcoal.registration import ModuleRegistration
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    EntryAddress,
    ExpectedDocument,
    Put,
    Rejected,
    entry_checksum,
    new_id,
)
from moarcoal.storage.expected_documents import MAX_YEAR, MIN_YEAR, TEXT_MAX
from moarcoal.web import form_fields, render, store_of, user_of

router = APIRouter(prefix="/erwartete-belege")

type Fields = dict[str, str]

HINTS = {
    "document_kind": "Dokumentart: aus der Liste wählen",
    "start_year": f"Beginn: Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
    "end_year": f"Ende: weglassen oder Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
    "description": f"Beschreibung: höchstens {TEXT_MAX} Zeichen",
}
END_BEFORE_START = "Ende: nicht vor dem Beginn"


def _all_kinds(request: Request) -> list[DocumentKind]:
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    return [k for r in registrations for k in r.document_kinds]


def _kinds(request: Request) -> dict[str, DocumentKind]:
    """Dokumentarten mit Bezugszeitraum; nur für sie lässt sich ein Jahr erwarten."""
    return {k.key: k for k in _all_kinds(request) if k.has_period}


def _build(
    request: Request, fields: Fields, owner: str, entry_id: str
) -> tuple[ExpectedDocument | None, list[str]]:
    kind = fields.get("document_kind", "")
    if kind not in _kinds(request):
        return None, [HINTS["document_kind"]]
    try:
        entry = ExpectedDocument.model_validate(
            {
                "id": entry_id,
                "owner": owner,
                "document_kind": kind,
                "start_year": fields.get("start_year", "").strip(),
                "end_year": fields.get("end_year", "").strip() or None,
                "description": fields.get("description", "").strip(),
            }
        )
    except ValidationError as error:
        names = list(dict.fromkeys(str(e["loc"][-1]) if e["loc"] else "" for e in error.errors()))
        return None, [HINTS.get(name, END_BEFORE_START) for name in names]
    return entry, []


def _prefill(entry: ExpectedDocument | None) -> Fields:
    if entry is None:
        return {"start_year": str(DEFAULT_YEAR)}
    return {
        "document_kind": entry.document_kind,
        "start_year": str(entry.start_year),
        "end_year": "" if entry.end_year is None else str(entry.end_year),
        "description": entry.description,
    }


def _own(request: Request, entry_id: str) -> ExpectedDocument:
    try:
        address = EntryAddress(kind=ExpectedDocument.__name__, id=entry_id)
    except ValueError as error:
        raise HTTPException(404) from error
    entry = store_of(request).state().get(address)
    if not isinstance(entry, ExpectedDocument) or entry.owner != user_of(request):
        raise HTTPException(404)
    return entry


def _overview(
    request: Request, errors: list[str], values: Fields, status_code: int = 200
) -> HTMLResponse:
    state = store_of(request).state()
    user = user_of(request)
    documents = [d for d in state.of_kind(Document) if d.owner == user]
    expected = sorted(
        (e for e in state.of_kind(ExpectedDocument) if e.owner == user),
        key=lambda e: (e.start_year, e.id),
    )
    rows = [(e, statuses(documents, e, DEFAULT_YEAR)) for e in expected]
    return render(
        request,
        "expected_documents/index.html",
        status_code,
        rows=rows,
        kinds=_kinds(request),
        titles={k.key: k.title for k in _all_kinds(request)},
        errors=errors,
        values=values,
    )


def _edit(
    request: Request,
    entry_id: str,
    fields: Fields,
    errors: list[str],
    checksum: str,
    status_code: int = 200,
) -> HTMLResponse:
    return render(
        request,
        "expected_documents/edit.html",
        status_code,
        entry_id=entry_id,
        kinds=_kinds(request),
        values=fields,
        checksum=checksum,
        errors=errors,
    )


def _reasons(result: Rejected) -> list[str]:
    return list(result.reasons.values())


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request, [], _prefill(None))


@router.post("")
def create(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    entry, errors = _build(request, fields, user_of(request), new_id())
    if entry is None:
        return _overview(request, errors, fields, 422)
    result = store_of(request).apply([Put(entry)])
    if not isinstance(result, Applied):
        return _overview(request, _reasons(result), fields, 409)
    return RedirectResponse("/erwartete-belege", status_code=303)


@router.get("/{entry_id}", response_class=HTMLResponse)
def edit_page(request: Request, entry_id: str) -> HTMLResponse:
    entry = _own(request, entry_id)
    return _edit(request, entry_id, _prefill(entry), [], entry_checksum(entry))


@router.post("/{entry_id}")
def update(
    request: Request, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    _own(request, entry_id)
    checksum = fields.get("checksum", "")
    entry, errors = _build(request, fields, user_of(request), entry_id)
    if entry is None:
        return _edit(request, entry_id, fields, errors, checksum, 422)
    result = store_of(request).apply([Put(entry, expected=checksum)])
    if not isinstance(result, Applied):
        return _edit(request, entry_id, fields, _reasons(result), checksum, 409)
    return RedirectResponse("/erwartete-belege", status_code=303)


@router.post("/{entry_id}/loeschen")
def delete(
    request: Request, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    entry = _own(request, entry_id)
    checksum = fields.get("checksum", "")
    result = store_of(request).apply([Delete(entry.address, expected=checksum)])
    if not isinstance(result, Applied):
        return _edit(request, entry_id, _prefill(entry), _reasons(result), checksum, 409)
    return RedirectResponse("/erwartete-belege", status_code=303)
