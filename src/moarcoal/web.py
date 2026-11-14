"""Gemeinsame Helfer der Seiten: Vorlagen, Nutzer, Stand und Formularfelder."""

from typing import Any
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.documents import DocumentKind
from moarcoal.incoming import all_site_files, incoming_files
from moarcoal.links import document_url, issuer_url
from moarcoal.personal_details import details_of
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Document, EntryAddress, ExpectedDocument, Issuer, State, Store
from moarcoal.values.engine import Values
from moarcoal.values.model import Amount, format_amount


def format_eur(cents: int) -> str:
    """Ganze Cent als deutscher Betrag, z. B. 123456 -> '1.234,56 €'."""
    return format_amount(Amount.eur_cents(cents))


def year_of(text: str, *, in_range: bool = False) -> int | None:
    """Das Jahr als ganze Zahl (Randleerzeichen egal); `None`, wenn `text` keine ist, mit
    `in_range` auch, wenn sie außerhalb von `MIN_YEAR` bis `MAX_YEAR` liegt."""
    try:
        year = int(text.strip())
    except ValueError:
        return None
    return year if not in_range or MIN_YEAR <= year <= MAX_YEAR else None


def entry_url(modules: tuple[ModuleRegistration, ...], address: EntryAddress) -> str | None:
    """Link zum Eintrag, wie das besitzende Modul ihn nennt; unbekannte Art: kein Link."""
    if address.kind == Document.__name__:  # Baustein der Datenebene
        return document_url(address.id)
    if address.kind == ExpectedDocument.__name__:  # Baustein der Datenebene
        return f"/belege/erwartet/{address.id}"
    if address.kind == Issuer.__name__:  # Baustein der Datenebene
        return issuer_url(address.id)
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


def user_name_of(request: Request) -> str | None:
    """Der Name des Nutzers aus seinen Angaben zur Person; `None`, solange es den Nutzer nicht
    gibt."""
    details = details_of(store_of(request).state(), user_of(request))
    return None if details is None else details.display_name


PAGES_WITHOUT_USER = frozenset({"/", "/person"})  # und /static (eigene Anwendung, keine Route)


def require_user(request: Request) -> None:
    """Ohne Nutzer (ohne Angaben zur Person) führt jede Seite außer der Startseite und den Angaben
    zur Person mit 303 auf die Startseite."""
    if request.url.path in PAGES_WITHOUT_USER:
        return  # diese Seiten können den Nutzer anlegen; `render` ermittelt den Namen dann selbst
    user_name = user_name_of(request)
    if user_name is None:
        raise HTTPException(303, headers={"Location": "/"})
    request.state.user_name = user_name  # `render` liest ihn hier, statt ihn neu zu ermitteln


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
    user_name = getattr(request.state, "user_name", None) or user_name_of(request)
    if "open_files" not in context:  # Zähler der Seitenleiste; die Belege-Seite kennt ihn schon
        store = store_of(request)
        context["open_files"] = (
            0
            if user_name is None
            else len(incoming_files(all_site_files(store), store.state(), user_of(request)))
        )
    return templates.TemplateResponse(
        request,
        name,
        {"modules": registrations, "user_name": user_name, **context},
        status_code=status_code,
    )
