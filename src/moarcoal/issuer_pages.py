"""Seite „Aussteller“: Katalog mit Suche, Detail mit Ändern, Zusammenführen, Löschen (Spec 3.2).

Gelöscht wird nur ohne Verweise; sonst zeigt die Seite die Verweise des Nutzers. Zusammenführen
läuft über eine Folgenseite und eine ausdrückliche Bestätigung; die App schlägt es nie vor.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.links import issuer_url
from moarcoal.personal_details import details_for_issuer
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    Merge,
    Put,
    Rejected,
    State,
    entry_checksum,
    name_key,
)
from moarcoal.storage.entries import referenced_addresses
from moarcoal.storage.issuers import issuer_with_name
from moarcoal.web import form_fields, render, store_of, user_of

router = APIRouter(prefix="/aussteller")

type Fields = dict[str, str]

FROM_DETAILS = "Der Aussteller kommt aus den Angaben zur Person."

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
    needle = name_key(query)
    return any(needle in name_key(name) for name in (issuer.name, *issuer.aliases))


def _build(fields: Fields, issuer: Issuer, locked: bool = False) -> tuple[Issuer | None, list[str]]:
    """Der geänderte Aussteller; Name und Privatperson bleiben, wenn er aus den Angaben zur
    Person kommt (`locked`)."""
    aliases = tuple(line.strip() for line in fields.get("aliases", "").splitlines() if line.strip())
    try:
        changed = Issuer.model_validate(
            {
                **issuer.model_dump(),
                "name": issuer.name if locked else fields.get("name", "").strip(),
                "aliases": aliases,
                "private_person": issuer.private_person
                if locked
                else fields.get("private_person") == "on",
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
    holder: Issuer | None = None,
) -> HTMLResponse:
    state = store_of(request).state()
    documents, expected = _references(state, issuer, user_of(request))
    return render(
        request,
        "issuers/show.html",
        status_code,
        issuer=issuer,
        others=sorted(
            (i for i in state.of_kind(Issuer) if i.id != issuer.id),
            key=lambda i: (name_key(i.name), i.id),
        ),
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
        holder=holder,
        from_details=details_for_issuer(state, issuer) is not None,
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
        for issuer in sorted(state.of_kind(Issuer), key=lambda i: (name_key(i.name), i.id))
        if _matches(issuer, query)
    ]
    return render(request, "issuers/index.html", rows=rows, query=query)


@router.get("/{issuer_id}", response_class=Response)
def show(request: Request, issuer_id: str) -> Response:
    try:
        address = EntryAddress(kind=Issuer.__name__, id=issuer_id)
    except ValueError as error:
        raise HTTPException(404) from error
    found = store_of(request).state().resolve(address)
    if isinstance(found, Issuer) and found.id != issuer_id:  # zusammengeführt: alte Adresse
        return RedirectResponse(issuer_url(found.id), status_code=308)
    return _detail(request, _issuer(request, issuer_id))


def _merge_page(
    request: Request,
    source: Issuer,
    target: Issuer | None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = store_of(request).state()
    user = user_of(request)
    documents, expected = _references(state, source, user)
    return render(
        request,
        "issuers/merge.html",
        status_code,
        source=source,
        target=target,
        checksum=entry_checksum(source),
        target_checksum=entry_checksum(target) if target else "",
        documents=documents,
        expected=expected,
        errors=errors or [],
    )


def _target(request: Request, source: Issuer, issuer_id: str) -> Issuer | None:
    try:
        address = EntryAddress(kind=Issuer.__name__, id=issuer_id)
    except ValueError:
        return None
    target = store_of(request).state().get(address)
    return target if isinstance(target, Issuer) and target.id != source.id else None


@router.get("/{issuer_id}/zusammenfuehren", response_class=HTMLResponse)
def merge_preview(request: Request, issuer_id: str, into: str = "") -> HTMLResponse:
    """Folgenseite: ändert nichts, zeigt nur, was das Zusammenführen bewirkt."""
    source = _issuer(request, issuer_id)
    target = _target(request, source, into)
    if target is None:
        raise HTTPException(404)
    return _merge_page(request, source, target)


@router.post("/{issuer_id}/zusammenfuehren")
def merge(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    source = _issuer(request, issuer_id)
    target = _target(request, source, fields.get("into", ""))
    if target is None:
        raise HTTPException(404)
    if fields.get("confirm") != "on":
        return _merge_page(request, source, target, ["Bitte das Zusammenführen bestätigen."], 422)
    result = store_of(request).apply(
        [
            Merge(
                source.address,
                target.address,
                expected=fields.get("checksum", ""),
                expected_into=fields.get("target_checksum", ""),
            )
        ]
    )
    if not isinstance(result, Applied):
        return _merge_page(request, source, target, _reasons(result), 409)
    return RedirectResponse(issuer_url(target.id), status_code=303)


@router.post("/{issuer_id}")
def update(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    locked = details_for_issuer(store_of(request).state(), issuer) is not None
    changed, errors = _build(fields, issuer, locked)
    if changed is None:
        return _detail(request, issuer, fields, errors, 422)
    result = store_of(request).apply([Put(changed, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        others = [i for i in store_of(request).state().of_kind(Issuer) if i.id != issuer.id]
        holder = next(
            (h for n in (changed.name, *changed.aliases) if (h := issuer_with_name(others, n))),
            None,
        )
        reasons = [] if holder else _reasons(result)
        return _detail(request, issuer, fields, reasons, 409, holder)
    return RedirectResponse(f"/aussteller/{issuer.id}", status_code=303)


@router.post("/{issuer_id}/loeschen")
def delete(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    if details_for_issuer(store_of(request).state(), issuer) is not None:
        return _detail(request, issuer, errors=[FROM_DETAILS], status_code=409)
    result = store_of(request).apply([Delete(issuer.address, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _detail(request, issuer, errors=_reasons(result), status_code=409)
    return RedirectResponse("/aussteller", status_code=303)
