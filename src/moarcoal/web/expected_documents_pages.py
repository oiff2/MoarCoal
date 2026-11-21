"""Erwartete Belege: anlegen, ändern, löschen; sie stehen als Abschnitt auf der Belege-Seite."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR
from moarcoal.documents import DocumentKind
from moarcoal.expected_documents import previous_year_issuer
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    ExpectedDocument,
    Issuer,
    Put,
    entry_checksum,
    new_id,
)
from moarcoal.storage.expected_documents import TEXT_MAX
from moarcoal.web.helpers import (
    document_kinds,
    entry_of,
    form_fields,
    rejection_reasons,
    render,
    store_of,
    user_of,
    validated,
)
from moarcoal.web.links import expected_documents_url
from moarcoal.web.site_pages import belege_page

router = APIRouter(prefix="/belege/erwartet")

type Fields = dict[str, str]

HINTS = {
    "document_kind": "Dokumentart: aus der Liste wählen",
    "start_year": f"Beginn: Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
    "end_year": f"Ende: weglassen oder Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
    "description": f"Beschreibung: höchstens {TEXT_MAX} Zeichen",
}
END_BEFORE_START = "Ende: nicht vor dem Beginn"


def _all_kinds(request: Request) -> list[DocumentKind]:
    return list(document_kinds(request).values())


def _kinds(request: Request) -> dict[str, DocumentKind]:
    """Dokumentarten mit Bezugszeitraum; nur für sie lässt sich ein Jahr erwarten."""
    return {k.key: k for k in _all_kinds(request) if k.has_period}


def _build(
    request: Request, fields: Fields, owner: str, entry_id: str
) -> tuple[ExpectedDocument | None, list[str]]:
    kind = fields.get("document_kind", "")
    if kind not in _kinds(request):
        return None, [HINTS["document_kind"]]
    return validated(
        ExpectedDocument,
        {
            "id": entry_id,
            "owner": owner,
            "document_kind": kind,
            "start_year": fields.get("start_year", "").strip(),
            "end_year": fields.get("end_year", "").strip() or None,
            "description": fields.get("description", "").strip(),
        },
        HINTS,
        END_BEFORE_START,
    )


def _prefill(entry: ExpectedDocument) -> Fields:
    return {
        "document_kind": entry.document_kind,
        "start_year": str(entry.start_year),
        "end_year": "" if entry.end_year is None else str(entry.end_year),
        "description": entry.description,
    }


def _own(request: Request, entry_id: str) -> ExpectedDocument:
    return entry_of(store_of(request).state(), ExpectedDocument, entry_id, user_of(request))


def _suggestion(request: Request, entry: ExpectedDocument) -> Issuer | None:
    """Aussteller des Vorjahres für das letzte angezeigte Jahr (bei offenem Ende `DEFAULT_YEAR`)."""
    state = store_of(request).state()
    user = user_of(request)
    documents = [d for d in state.of_kind(Document) if d.owner == user]
    year = entry.end_year if entry.end_year is not None else max(DEFAULT_YEAR, entry.start_year)
    address = previous_year_issuer(documents, entry, year)
    found = None if address is None else state.resolve(address)
    return found if isinstance(found, Issuer) else None


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
        suggestion=_suggestion(request, _own(request, entry_id)),
        kinds=_kinds(request),
        values=fields,
        checksum=checksum,
        errors=errors,
    )


@router.get("")
def moved() -> RedirectResponse:
    """Die Erwarteten Belege sind ein Abschnitt der Belege-Seite."""
    return RedirectResponse(expected_documents_url(), status_code=308)


@router.post("")
def create(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    entry, errors = _build(request, fields, user_of(request), new_id())
    if entry is None:
        return belege_page(request, 422, expected_errors=errors, expected_values=fields)
    result = store_of(request).apply([Put(entry)])
    if not isinstance(result, Applied):
        return belege_page(
            request, 409, expected_errors=rejection_reasons(result), expected_values=fields
        )
    return RedirectResponse(expected_documents_url(), status_code=303)


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
        return _edit(request, entry_id, fields, rejection_reasons(result), checksum, 409)
    return RedirectResponse(expected_documents_url(), status_code=303)


@router.post("/{entry_id}/loeschen")
def delete(
    request: Request, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    entry = _own(request, entry_id)
    checksum = fields.get("checksum", "")
    result = store_of(request).apply([Delete(entry.address, expected=checksum)])
    if not isinstance(result, Applied):
        return _edit(request, entry_id, _prefill(entry), rejection_reasons(result), checksum, 409)
    return RedirectResponse(expected_documents_url(), status_code=303)
