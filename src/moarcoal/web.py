"""Gemeinsame Helfer der Seiten: Vorlagen, Nutzer, Stand und Formularfelder."""

from typing import Any
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from moarcoal.documents import DocumentKind
from moarcoal.incoming import all_site_files
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import EntryAddress, ExpectedDocument, State, Store
from moarcoal.values.engine import Values
from moarcoal.values.model import Amount, format_amount


def format_eur(cents: int) -> str:
    """Ganze Cent als deutscher Betrag, z. B. 123456 -> '1.234,56 €'."""
    return format_amount(Amount.eur_cents(cents))


def entry_url(modules: tuple[ModuleRegistration, ...], address: EntryAddress) -> str | None:
    """Link zum Eintrag, wie das besitzende Modul ihn nennt; unbekannte Art: kein Link."""
    if address.kind == ExpectedDocument.__name__:  # Baustein der Datenebene
        return f"/erwartete-belege/{address.id}"
    return next((url for m in modules if (url := m.entry_url(address)) is not None), None)


def values_on(request: Request, state: State) -> Values:
    """`Values` der Anwendung auf einem beliebigen Stand (z. B. einem vorläufigen)."""
    store = store_of(request)
    return Values(request.app.state.modules, state, site_files=lambda: all_site_files(store))


def values_of(request: Request) -> Values:
    """`Values` der Anfrage, auf dem Stand zu Beginn der Anfrage."""
    return values_on(request, store_of(request).state())


def document_kinds(request: Request) -> dict[str, DocumentKind]:
    """Alle Dokumentarten aller Modulanmeldungen, nach Schlüssel."""
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    return {k.key: k for r in registrations for k in r.document_kinds}


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
        {"modules": registrations, "user_name": request.app.state.user_name,
         "variant": request.query_params.get("variant", "A"), **context},
        status_code=status_code,
    )
