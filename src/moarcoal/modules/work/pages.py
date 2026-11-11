"""Seiten des Moduls Arbeit: erfassen, ändern, löschen. Geschrieben wird nur über `apply`."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from moarcoal.modules.work.entries import (
    DEFAULT_WORKDAYS,
    MAX_WORKDAYS,
    FirstWorkplace,
    UserInput,
    WorkEquipment,
)
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Applied,
    Delete,
    Entry,
    EntryAddress,
    Put,
    entry_checksum,
    new_id,
)
from moarcoal.web import form_fields, module_state, render, store_of, user_of

MODULE_KEY = "work"
router = APIRouter(prefix="/arbeit")

type Fields = dict[str, str]
type Build = Callable[[Fields, str, str], tuple[Entry | None, list[str]]]

# Hinweis je Feld, wenn die Prüfung es ablehnt (Pydantic liefert nur englische Meldungen).
HINTS = {
    "year": "Steuerjahr: Jahr zwischen 2000 und 2100",
    "workdays": f"Arbeitstage: ganze Zahl von 0 bis {MAX_WORKDAYS}",
    "distance_km": "Einfache Entfernung: ganze Zahl von 0 bis 1000 km",
    "description": "Beschreibung: höchstens 200 Zeichen",
    "amount_cents": "Betrag: größer als 0, mit höchstens zwei Nachkommastellen, z. B. 49,90",
    "date": "Datum: gültiges Datum",
}
REQUIRED_DESCRIPTION = "Beschreibung: angeben, höchstens 200 Zeichen"


def parse_cents(text: str) -> int:
    """'1.234,56' oder '49,9' -> Cent; wirft `ValueError` bei allem anderen."""
    cleaned = text.strip().replace(".", "").replace(",", ".")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(text) from error
    cents = amount * 100
    if not amount.is_finite() or cents != cents.to_integral_value():
        raise ValueError(text)
    return int(cents)


def _errors(error: ValidationError, required_description: bool) -> list[str]:
    fields = [str(e["loc"][-1]) for e in error.errors()]
    messages = [HINTS.get(name, name) for name in dict.fromkeys(fields)]
    if required_description and "description" in fields:
        messages = [REQUIRED_DESCRIPTION if m == HINTS["description"] else m for m in messages]
    return messages


def build_workplace(fields: Fields, owner: str, entry_id: str) -> tuple[Entry | None, list[str]]:
    try:
        entry = FirstWorkplace.model_validate(
            {
                "id": entry_id,
                "owner": owner,
                "year": fields.get("year", ""),
                "workdays": fields.get("workdays", ""),
                "distance_km": fields.get("distance_km", ""),
                "description": fields.get("description", "").strip(),
            }
        )
    except ValidationError as error:
        return None, _errors(error, required_description=False)
    return entry, []


def build_equipment(fields: Fields, owner: str, entry_id: str) -> tuple[Entry | None, list[str]]:
    try:
        cents = parse_cents(fields.get("amount", ""))
    except ValueError:
        cents = 0  # die Prüfung unten meldet den Betrag
    try:
        entry = WorkEquipment.model_validate(
            {
                "id": entry_id,
                "owner": owner,
                "year": fields.get("year", ""),
                "input": UserInput.model_validate(
                    {
                        "amount_cents": cents,
                        "date": fields.get("date", ""),
                        "description": fields.get("description", "").strip(),
                    }
                ).model_dump(),
            }
        )
    except ValidationError as error:
        return None, _errors(error, required_description=True)
    return entry, []


class Kind:
    def __init__(self, slug: str, title: str, model: type[Entry], build: Build) -> None:
        self.slug = slug
        self.title = title
        self.model = model
        self.build = build


KINDS = {
    "erste-taetigkeitsstaette": Kind(
        "erste-taetigkeitsstaette", "Erste Tätigkeitsstätte", FirstWorkplace, build_workplace
    ),
    "arbeitsmittel": Kind("arbeitsmittel", "Arbeitsmittel", WorkEquipment, build_equipment),
}


def _kind(slug: str) -> Kind:
    kind = KINDS.get(slug)
    if kind is None:
        raise HTTPException(404)
    return kind


def _address(kind: Kind, entry_id: str) -> EntryAddress:
    try:
        return EntryAddress(kind=kind.model.__name__, id=entry_id)
    except ValueError as error:
        raise HTTPException(404) from error


def _own_state(request: Request) -> ModuleState:
    return module_state(request, MODULE_KEY)


def _new_values(slug: str) -> Fields:
    """Vorbelegung eines neuen Formulars."""
    if slug == "erste-taetigkeitsstaette":
        return {"year": "2025", "workdays": str(DEFAULT_WORKDAYS)}
    return {"year": "2025"}


def _values(entry: Entry | None) -> Fields:
    """Vorbelegung der Formularfelder aus einem Eintrag."""
    match entry:
        case FirstWorkplace():
            return {
                "year": str(entry.year),
                "workdays": str(entry.workdays),
                "distance_km": str(entry.distance_km),
                "description": entry.description,
            }
        case WorkEquipment():
            euros, cents = divmod(entry.input.amount_cents, 100)
            return {
                "year": str(entry.year),
                "amount": f"{euros},{cents:02d}",
                "date": entry.input.date.isoformat(),
                "description": entry.input.description,
            }
        case _:
            return {"year": "2025"}


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
        workplaces=[(e, entry_checksum(e)) for e in state.all(FirstWorkplace)],
        equipment=[(e, entry_checksum(e)) for e in state.all(WorkEquipment)],
        kinds=KINDS,
        errors=errors,
        values=values,
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _overview(request, {}, {s: _new_values(s) for s in KINDS})


@router.get("/{slug}/{entry_id}", response_class=HTMLResponse)
def edit_page(request: Request, slug: str, entry_id: str) -> HTMLResponse:
    kind = _kind(slug)
    address = _address(kind, entry_id)
    state = _own_state(request)
    entry = state.get(address)
    if entry is None:
        raise HTTPException(404)
    return render(
        request,
        "work/edit.html",
        kind=kind,
        entry=entry,
        values=_values(entry),
        checksum=entry_checksum(entry),
        errors=[],
    )


def _edit_response(
    request: Request, kind: Kind, entry_id: str, fields: Fields, errors: list[str], status: int
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
            {s: fields if s == slug else _new_values(s) for s in KINDS},
            422,
        )
    result = store_of(request).apply([Put(entry)])
    if not isinstance(result, Applied):
        reasons = list(result.reasons.values())
        return _overview(
            request,
            {slug: reasons},
            {s: fields if s == slug else _new_values(s) for s in KINDS},
            409,
        )
    return RedirectResponse("/arbeit", status_code=303)


@router.post("/{slug}/{entry_id}")
def update(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    address = _address(kind, entry_id)
    if _own_state(request).get(address) is None:
        raise HTTPException(404)
    entry, errors = kind.build(fields, user_of(request), entry_id)
    if entry is None:
        return _edit_response(request, kind, entry_id, fields, errors, 422)
    result = store_of(request).apply([Put(entry, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        reasons = list(result.reasons.values())
        return _edit_response(request, kind, entry_id, fields, reasons, 409)
    return RedirectResponse("/arbeit", status_code=303)


@router.post("/{slug}/{entry_id}/loeschen")
def delete(
    request: Request, slug: str, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    kind = _kind(slug)
    address = _address(kind, entry_id)
    if _own_state(request).get(address) is None:
        raise HTTPException(404)
    result = store_of(request).apply([Delete(address, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        reasons = list(result.reasons.values())
        return _edit_response(request, kind, entry_id, fields, reasons, 409)
    return RedirectResponse("/arbeit", status_code=303)
