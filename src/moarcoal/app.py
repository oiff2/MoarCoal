"""App-Fabrik: FastAPI mit Jinja2-Vorlagen, lokal ausgeliefertem htmx und den Modulen."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from moarcoal.defaults import year_of
from moarcoal.document_list import router as document_list_router
from moarcoal.document_pages import router as document_router
from moarcoal.documents import read_in_again
from moarcoal.expected_documents_pages import router as expected_documents_router
from moarcoal.extraction import ClaudeExtractor, Extractor
from moarcoal.findings_pages import router as findings_router
from moarcoal.issuer_field_pages import router as issuer_field_router
from moarcoal.issuer_pages import router as issuer_router
from moarcoal.modules import MODULES
from moarcoal.person_pages import router as person_router
from moarcoal.place_search import NominatimSearch, PlaceSearch
from moarcoal.previews import preview_kind
from moarcoal.registration import ModuleRegistration
from moarcoal.security import SecurityMiddleware
from moarcoal.site_pages import moved_router
from moarcoal.site_pages import router as belege_router
from moarcoal.storage import open_store
from moarcoal.values.model import format_amount
from moarcoal.web import (
    YEAR_COOKIE,
    entry_url,
    form_fields,
    format_eur,
    require_user,
)

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
# Durchstich: ein fester Nutzer; Nutzerliste und Nutzerwechsel kommen mit dem Prototyp (#62).
DEFAULT_USER = "ich"
log = logging.getLogger(__name__)


def create_app(
    port: int,
    data_dir: Path,
    modules: Sequence[ModuleRegistration] = MODULES,
    user: str = DEFAULT_USER,
    extractor: Extractor | None = None,
    place_search: PlaceSearch | None = None,
) -> FastAPI:
    """`data_dir` wird immer übergeben; `default_data_dir()` gilt nur beim Start der App."""
    app = FastAPI(
        docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(require_user)]
    )
    app.add_middleware(SecurityMiddleware, port=port)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    environment = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    environment.filters["eur"] = format_eur
    environment.filters["amount"] = format_amount
    globals_: dict[str, Any] = environment.globals  # pyright: ignore[reportAssignmentType]
    globals_["preview_kind"] = preview_kind
    globals_["entry_url"] = lambda address: entry_url(app.state.modules, address)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    app.state.templates = Jinja2Templates(env=environment)
    app.state.modules = tuple(modules)
    app.state.user = user
    # Die App bekommt den echten Baustein, Tests einen Fake; aufgerufen wird nur auf Wunsch.
    app.state.extractor = extractor if extractor is not None else ClaudeExtractor()
    # Ebenso die Ortssuche: der echte Baustein fragt nur nach Klick auf „Suchen“ (ADR 0008).
    app.state.place_search = place_search if place_search is not None else NominatimSearch()
    app.state.store = open_store(
        data_dir,
        [kind for module in modules for kind in module.kinds],
        once_per_period={
            kind.key: kind.title
            for module in modules
            for kind in module.document_kinds
            if kind.unique_per_period
        },
        kinds_with_period={k.key for m in modules for k in m.document_kinds if k.has_period},
    )
    document_kinds = {k.key: k for module in modules for k in module.document_kinds}
    for line in read_in_again(app.state.store, document_kinds):  # Start, Schritt 5
        log.info(line)
    for module in modules:
        app.include_router(module.router)
    app.include_router(belege_router)
    app.include_router(moved_router)
    app.include_router(document_list_router)
    app.include_router(document_router)
    app.include_router(expected_documents_router)
    app.include_router(issuer_router)
    app.include_router(issuer_field_router)
    app.include_router(person_router)
    app.include_router(findings_router)

    @app.post("/jahr")
    def choose_year(  # pyright: ignore[reportUnusedFunction]
        fields: Annotated[dict[str, str], Depends(form_fields)],
    ) -> Response:
        """Das globale Jahr wählen (Kopfleiste) und zurück zur Seite, nur innerhalb der App."""
        year = year_of(fields.get("year", ""), in_range=True)
        if year is None:
            raise HTTPException(422, "Jahr fehlt oder liegt außerhalb des Bereichs.")
        back = fields.get("back", "")
        own = back.startswith("/") and not back.startswith(("//", "/\\"))
        response = RedirectResponse(back if own else "/", status_code=303)
        response.set_cookie(YEAR_COOKIE, str(year), httponly=True, samesite="strict")
        return response

    return app
