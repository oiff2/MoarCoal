"""Startseite und Seite „Angaben zur Person“ (docs/grundgeruest.md, 3.2 und 6; ADR 0009).

Beide zeigen dieselbe Teilvorlage `person/_form.html`. Ohne Nutzer ist die Startseite die einzige
Seite mit Inhalt; das Speichern legt den Nutzer an.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.personal_details import PersonalDetailsInvalid, details_of, personal_details_changes
from moarcoal.storage import Applied, entry_checksum
from moarcoal.web import form_fields, render, store_of, user_of

router = APIRouter()

type Fields = dict[str, str]


def _page(
    request: Request,
    template: str,
    fields: Fields | None = None,
    errors: list[str] | None = None,
    status: int = 200,
) -> HTMLResponse:
    details = details_of(store_of(request).state(), user_of(request))
    values = fields or (
        {}
        if details is None
        else {"first_name": details.first_name, "last_name": details.last_name}
    )
    return render(
        request,
        template,
        status,
        values=values,
        checksum="" if details is None else entry_checksum(details),
        errors=errors or [],
    )


@router.get("/", response_class=HTMLResponse)
def start(request: Request) -> HTMLResponse:
    return _page(request, "start.html")


@router.get("/person", response_class=HTMLResponse)
def show(request: Request) -> HTMLResponse:
    return _page(request, "person/show.html")


@router.post("/person")
def save(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    store = store_of(request)
    user = user_of(request)
    created = details_of(store.state(), user) is None
    template = "start.html" if created else "person/show.html"
    try:
        changes = personal_details_changes(
            store.state(),
            user,
            fields.get("first_name", ""),
            fields.get("last_name", ""),
            fields.get("checksum", ""),
        )
    except PersonalDetailsInvalid as error:
        return _page(request, template, fields, error.problems, 422)
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _page(request, template, fields, list(result.reasons.values()), 409)
    return RedirectResponse("/" if created else "/person", status_code=303)
