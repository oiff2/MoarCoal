"""Startseite und Seite „Angaben zur Person“ (docs/grundgeruest.md, 3.2 und 6; ADR 0009).

Beide zeigen dieselbe Teilvorlage `person/_form.html`. Ohne Nutzer ist die Startseite die einzige
Seite mit Inhalt; das Speichern legt den Nutzer an.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.personal_details import (
    PersonalDetailsInvalid,
    PersonForm,
    details_of,
    personal_details_changes,
)
from moarcoal.storage import Applied, PersonalDetails, Religion, entry_checksum
from moarcoal.web.helpers import form_fields, rejection_reasons, render, store_of, user_of

router = APIRouter()

type Fields = dict[str, str]


_TEXT_FIELDS = (
    "birth_date",
    "id_number",
    "title",
    "street",
    "house_number",
    "postal_code",
    "city",
    "iban",
    "account_holder",
)


def _stored_values(details: PersonalDetails) -> Fields:
    """Die gespeicherten Angaben als Formularwerte, dazu je Religionsangabe ein Zeilenpaar."""
    values: Fields = {"first_name": details.first_name, "last_name": details.last_name}
    for name in _TEXT_FIELDS:
        values[name] = str(getattr(details, name) or "")
    for index, member in enumerate(details.religions):
        values[f"religion_from_{index}"] = member.from_date.isoformat()
        values[f"religion_{index}"] = member.religion.value
    return values


def _religion_rows(values: Fields) -> list[tuple[str, str]]:
    """Die Zeilen der Religionsangaben aus den Formularwerten, dazu eine leere zum Ergänzen."""
    rows: list[tuple[str, str]] = []
    index = 0
    while f"religion_from_{index}" in values or f"religion_{index}" in values:
        rows.append((values.get(f"religion_from_{index}", ""), values.get(f"religion_{index}", "")))
        index += 1
    return [*(row for row in rows if any(row)), ("", "")]


def _more(fields: Fields) -> PersonForm | None:
    """Die übrigen Angaben des Formulars; das Startformular (nur Name) schickt sie nicht."""
    if "extended" not in fields:
        return None
    rows = tuple(_religion_rows(fields)[:-1])
    return PersonForm(**{name: fields.get(name, "") for name in _TEXT_FIELDS}, religions=rows)


def _page(
    request: Request,
    template: str,
    fields: Fields | None = None,
    errors: list[str] | None = None,
    status: int = 200,
) -> HTMLResponse:
    details = details_of(store_of(request).state(), user_of(request))
    values = fields or ({} if details is None else _stored_values(details))
    return render(
        request,
        template,
        status,
        values=values,
        checksum="" if details is None else entry_checksum(details),
        errors=errors or [],
        religion_rows=_religion_rows(values),
        religion_choices=[r.value for r in Religion],
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
            more=_more(fields),
        )
    except PersonalDetailsInvalid as error:
        return _page(request, template, fields, error.problems, 422)
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _page(request, template, fields, rejection_reasons(result), 409)
    return RedirectResponse("/" if created else "/person", status_code=303)
