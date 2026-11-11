"""Gemeinsame Helfer der Seiten: Vorlagen, Nutzer, Stand und Formularfelder."""

from typing import Any
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Store


def format_eur(cents: int) -> str:
    """Ganze Cent als deutscher Betrag, z. B. 123456 -> '1.234,56 €'."""
    euros, rest = divmod(abs(cents), 100)
    text = f"{euros:,}".replace(",", ".") + f",{rest:02d} €"
    return "-" + text if cents < 0 else text


def store_of(request: Request) -> Store:
    return request.app.state.store


def user_of(request: Request) -> str:
    return request.app.state.user


def module_state(request: Request, key: str) -> ModuleState:
    """Der Stand der Anfrage, eingegrenzt auf das Modul `key` und den Nutzer."""
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    registration = next(r for r in registrations if r.key == key)
    return ModuleState(store_of(request).state(), registration, user_of(request))


async def form_fields(request: Request) -> dict[str, str]:
    """Felder eines Formulars (application/x-www-form-urlencoded), je Feld der erste Wert."""
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = parse_qs(body, keep_blank_values=True)
    return {name: values[0] for name, values in parsed.items()}


def render(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    return templates.TemplateResponse(
        request,
        name,
        {"modules": registrations, "user_name": request.app.state.user_name, **context},
        status_code=status_code,
    )
