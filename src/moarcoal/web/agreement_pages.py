"""Seite „Verträge“: Liste mit Anlegen, Detail mit Ändern, Dokumenten zuordnen, Löschen (Spec 3.2).

Gelöscht wird nur, solange nichts auf den Vertrag verweist (die Dokumente sind zuerst zu lösen);
das prüft `Store.apply`, die Seite zeigt den Knopf nur ohne Verweise.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.agreements import (
    AgreementInvalid,
    agreement_changes,
    agreements_of,
    assign,
    documents_of_agreement,
    unassign,
)
from moarcoal.issuer_field import IssuerChoice, resolve_issuer
from moarcoal.storage import (
    Agreement,
    Applied,
    Delete,
    Document,
    Issuer,
    entry_checksum,
    new_id,
)
from moarcoal.storage.agreements import CATEGORIES
from moarcoal.web.helpers import (
    entry_of,
    form_fields,
    rejection_reasons,
    render,
    store_of,
    user_of,
)
from moarcoal.web.links import agreement_url, agreements_url

router = APIRouter(prefix="/vertraege")

type Fields = dict[str, str]

FIELD_NAMES = ("name", "number", "category", "start", "end")


def _prefill(agreement: Agreement | None) -> Fields:
    if agreement is None:
        return {}
    return {
        "name": agreement.name,
        "number": agreement.number,
        "category": agreement.category,
        "start": agreement.start.isoformat() if agreement.start else "",
        "end": agreement.end.isoformat() if agreement.end else "",
    }


def _own(request: Request, agreement_id: str) -> Agreement:
    return entry_of(store_of(request).state(), Agreement, agreement_id, user_of(request))


def _overview(
    request: Request, errors: list[str], values: Fields, status_code: int = 200
) -> HTMLResponse:
    state = store_of(request).state()
    user = user_of(request)
    counts: dict[str, int] = {}
    for document in state.of_kind(Document):
        if document.owner == user:
            for target in document.assignments:
                counts[target.id] = counts.get(target.id, 0) + 1
    rows = [
        (agreement, state.get(agreement.issuer), counts.get(agreement.id, 0))
        for agreement in agreements_of(state, user)
    ]
    return render(
        request,
        "agreements/index.html",
        status_code,
        rows=rows,
        errors=errors,
        values=values,
        categories=CATEGORIES,
        issuer_text=values.get("issuer_text", ""),
    )


def _detail(
    request: Request,
    agreement: Agreement,
    values: Fields | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
    checksum: str | None = None,
) -> HTMLResponse:
    state = store_of(request).state()
    documents = documents_of_agreement(state, agreement)
    assigned = {d.id for d in documents}
    candidates = sorted(
        (d for d in state.of_kind(Document) if d.owner == agreement.owner and d.id not in assigned),
        key=lambda d: (d.site, d.path, d.id),
    )
    issuer = state.get(agreement.issuer)
    return render(
        request,
        "agreements/show.html",
        status_code,
        agreement=agreement,
        issuer=issuer if isinstance(issuer, Issuer) else None,
        documents=documents,
        candidates=candidates,
        checksum=checksum or entry_checksum(agreement),
        values=values if values is not None else _prefill(agreement),
        categories=CATEGORIES,
        issuer_text=(values or {}).get("issuer_text", ""),
        errors=errors or [],
    )


def _choice(request: Request, fields: Fields) -> IssuerChoice | str:
    return resolve_issuer(store_of(request).state(), fields)


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request, [], {})


@router.post("")
def create(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    choice = _choice(request, fields)
    if isinstance(choice, str):
        return _overview(request, [choice], fields, 422)
    entry_id = new_id()
    try:
        changes = agreement_changes(user_of(request), entry_id, choice, fields)
    except AgreementInvalid as error:
        return _overview(request, error.problems, fields, 422)
    result = store_of(request).apply(changes)
    if not isinstance(result, Applied):
        return _overview(request, rejection_reasons(result), fields, 409)
    return RedirectResponse(agreement_url(entry_id), status_code=303)


@router.get("/{agreement_id}", response_class=HTMLResponse)
def show(request: Request, agreement_id: str) -> HTMLResponse:
    return _detail(request, _own(request, agreement_id))


@router.post("/{agreement_id}")
def update(
    request: Request, agreement_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    agreement = _own(request, agreement_id)
    checksum = fields.get("checksum", "")
    choice = _choice(request, fields)
    if isinstance(choice, str):
        return _detail(request, agreement, fields, [choice], 422, checksum)
    try:
        changes = agreement_changes(agreement.owner, agreement.id, choice, fields, checksum)
    except AgreementInvalid as error:
        return _detail(request, agreement, fields, error.problems, 422, checksum)
    result = store_of(request).apply(changes)
    if not isinstance(result, Applied):
        return _detail(request, agreement, fields, rejection_reasons(result), 409, checksum)
    return RedirectResponse(agreement_url(agreement.id), status_code=303)


@router.post("/{agreement_id}/loeschen")
def delete(
    request: Request, agreement_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    agreement = _own(request, agreement_id)
    result = store_of(request).apply([Delete(agreement.address, fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        assigned = len(documents_of_agreement(store_of(request).state(), agreement))
        reasons = (
            [f"{assigned} {'Dokument' if assigned == 1 else 'Dokumente'} zugeordnet – erst lösen"]
            if assigned
            else rejection_reasons(result)
        )
        return _detail(request, agreement, errors=reasons, status_code=409)
    return RedirectResponse(agreements_url(), status_code=303)


@router.post("/{agreement_id}/dokumente")
def assign_document(
    request: Request, agreement_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    """Ein Dokument des Nutzers dem Vertrag zuordnen."""
    agreement = _own(request, agreement_id)
    document = entry_of(
        store_of(request).state(), Document, fields.get("document", ""), user_of(request)
    )
    result = store_of(request).apply([assign(document, agreement.address)])
    if not isinstance(result, Applied):
        return _detail(request, agreement, errors=rejection_reasons(result), status_code=409)
    return RedirectResponse(agreement_url(agreement.id), status_code=303)


@router.post("/{agreement_id}/dokumente/{document_id}/loesen")
def unassign_document(request: Request, agreement_id: str, document_id: str) -> Response:
    """Die Zuordnung eines Dokuments zum Vertrag lösen; das Dokument bleibt."""
    agreement = _own(request, agreement_id)
    document = entry_of(store_of(request).state(), Document, document_id, user_of(request))
    result = store_of(request).apply([unassign(document, agreement.address)])
    if not isinstance(result, Applied):
        return _detail(request, agreement, errors=rejection_reasons(result), status_code=409)
    return RedirectResponse(agreement_url(agreement.id), status_code=303)
