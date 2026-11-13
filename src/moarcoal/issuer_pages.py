"""Seite „Aussteller“: Katalog mit Suche, Detail mit Ändern und Löschen (docs/grundgeruest.md, 3.2).

Gelöscht wird nur ohne Verweise; sonst zeigt die Seite die Verweise des Nutzers.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    Put,
    Rejected,
    State,
    entry_checksum,
)
from moarcoal.storage.entries import referenced_addresses
from moarcoal.web import form_fields, render, store_of, user_of

router = APIRouter(prefix="/aussteller")

type Fields = dict[str, str]

HINTS = {
    "name": "Name: darf nicht leer sein",
    "aliases": "Weitere Namen: einer pro Absatz, keiner leer",
}


def _references(
    state: State, issuer: Issuer, user: str
) -> tuple[list[Document], list[ExpectedDocument]]:
    """Dokumente und Erwartete Belege des Nutzers, die auf den Aussteller verweisen."""
    found = [
        e
        for e in state.entries.values()
        if e.owner == user and issuer.address in referenced_addresses(e)
    ]
    documents = sorted((e for e in found if isinstance(e, Document)), key=lambda d: d.path)
    expected = sorted(
        (e for e in found if isinstance(e, ExpectedDocument)), key=lambda e: (e.start_year, e.id)
    )
    return documents, expected


def _matches(issuer: Issuer, query: str) -> bool:
    needle = query.casefold()
    return any(needle in name.casefold() for name in (issuer.name, *issuer.aliases))


def _build(fields: Fields, issuer: Issuer) -> tuple[Issuer | None, list[str]]:
    aliases = tuple(line.strip() for line in fields.get("aliases", "").splitlines() if line.strip())
    try:
        changed = Issuer.model_validate(
            {
                **issuer.model_dump(),
                "name": fields.get("name", "").strip(),
                "aliases": aliases,
                "private_person": fields.get("private_person") == "on",
            }
        )
    except ValidationError as error:
        names = {str(e["loc"][0]) for e in error.errors() if e["loc"]}
        return None, [hint for name, hint in HINTS.items() if name in names]
    return changed, []


def _issuer(request: Request, issuer_id: str) -> Issuer:
    try:
        address = EntryAddress(kind=Issuer.__name__, id=issuer_id)
    except ValueError as error:
        raise HTTPException(404) from error
    issuer = store_of(request).state().get(address)
    if not isinstance(issuer, Issuer):
        raise HTTPException(404)
    return issuer


def _detail(
    request: Request,
    issuer: Issuer,
    fields: Fields | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    documents, expected = _references(store_of(request).state(), issuer, user_of(request))
    return render(
        request,
        "issuers/show.html",
        status_code,
        issuer=issuer,
        checksum=entry_checksum(issuer),
        values=fields
        or {
            "name": issuer.name,
            "aliases": "\n".join(issuer.aliases),
            "private_person": "on" if issuer.private_person else "",
        },
        documents=documents,
        expected=expected,
        errors=errors or [],
    )


def _reasons(result: Rejected) -> list[str]:
    return list(result.reasons.values())


@router.get("", response_class=HTMLResponse)
def index(request: Request, q: str = "") -> HTMLResponse:
    query = q.strip()
    state = store_of(request).state()
    user = user_of(request)
    rows = [
        (issuer, *(len(refs) for refs in _references(state, issuer, user)))
        for issuer in sorted(state.of_kind(Issuer), key=lambda i: (i.name.casefold(), i.id))
        if _matches(issuer, query)
    ]
    return render(request, "issuers/index.html", rows=rows, query=query)


@router.get("/{issuer_id}", response_class=HTMLResponse)
def show(request: Request, issuer_id: str) -> HTMLResponse:
    return _detail(request, _issuer(request, issuer_id))


@router.post("/{issuer_id}")
def update(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    changed, errors = _build(fields, issuer)
    if changed is None:
        return _detail(request, issuer, fields, errors, 422)
    result = store_of(request).apply([Put(changed, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _detail(request, issuer, fields, _reasons(result), 409)
    return RedirectResponse(f"/aussteller/{issuer.id}", status_code=303)


@router.post("/{issuer_id}/loeschen")
def delete(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    result = store_of(request).apply([Delete(issuer.address, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _detail(request, issuer, errors=_reasons(result), status_code=409)
    return RedirectResponse("/aussteller", status_code=303)
