"""App-Fabrik: FastAPI mit Jinja2-Vorlagen, lokal ausgeliefertem htmx und den Modulen."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.dismissals import NoteMissing, dismiss, undismiss
from moarcoal.document_list import router as document_list_router
from moarcoal.document_pages import router as document_router
from moarcoal.expected_documents_pages import router as expected_documents_router
from moarcoal.extraction import ClaudeExtractor, Extractor
from moarcoal.issuer_field import router as issuer_field_router
from moarcoal.issuer_pages import router as issuer_router
from moarcoal.modules import MODULES
from moarcoal.registration import ModuleRegistration
from moarcoal.security import SecurityMiddleware
from moarcoal.site_pages import moved_router
from moarcoal.site_pages import router as belege_router
from moarcoal.storage import Applied, open_store
from moarcoal.values.model import format_amount
from moarcoal.web import (
    entry_url,
    form_fields,
    format_eur,
    render,
    store_of,
    user_of,
    values_of,
    year_of,
)

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
# Durchstich: ein Nutzer, die Nutzerliste kommt später; der Anzeigename ist erfunden.
DEFAULT_USER = "ich"
DEFAULT_USER_NAME = "Max Mustermann"


def _required_year(fields: dict[str, str]) -> int:
    year = year_of(fields.get("year", ""))
    if year is None:
        raise HTTPException(422, "Jahr fehlt oder ist keine Zahl.")
    return year


def create_app(
    port: int,
    data_dir: Path,
    modules: Sequence[ModuleRegistration] = MODULES,
    user: str = DEFAULT_USER,
    user_name: str = DEFAULT_USER_NAME,
    extractor: Extractor | None = None,
) -> FastAPI:
    """`data_dir` wird immer übergeben; `default_data_dir()` gilt nur beim Start der App."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityMiddleware, port=port)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    environment = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    environment.filters["eur"] = format_eur
    environment.filters["amount"] = format_amount
    globals_: dict[str, Any] = environment.globals  # pyright: ignore[reportAssignmentType]
    globals_["entry_url"] = lambda address: entry_url(app.state.modules, address)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    app.state.templates = Jinja2Templates(env=environment)
    app.state.modules = tuple(modules)
    app.state.user = user
    app.state.user_name = user_name
    # Die App bekommt den echten Baustein, Tests einen Fake; aufgerufen wird nur auf Wunsch.
    app.state.extractor = extractor if extractor is not None else ClaudeExtractor()
    app.state.store = open_store(
        data_dir,
        [kind for module in modules for kind in module.kinds],
        once_per_period={
            kind.key: kind.title
            for module in modules
            for kind in module.document_kinds
            if kind.unique_per_period
        },
    )
    for module in modules:
        app.include_router(module.router)
    app.include_router(belege_router)
    app.include_router(moved_router)
    app.include_router(document_list_router)
    app.include_router(document_router)
    app.include_router(expected_documents_router)
    app.include_router(issuer_router)
    app.include_router(issuer_field_router)

    @app.get("/", response_class=HTMLResponse)
    def start(request: Request) -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return render(request, "start.html")

    @app.get("/befunde", response_class=HTMLResponse)
    def findings(  # pyright: ignore[reportUnusedFunction]
        request: Request, year: int = DEFAULT_YEAR, ausgeblendet: int = 0
    ) -> HTMLResponse:
        return _findings_page(request, year, show_hidden=bool(ausgeblendet))

    def _findings_page(
        request: Request,
        year: int,
        show_hidden: bool = False,
        status_code: int = 200,
        notice: str = "",
        error: tuple[str, str] | None = None,
        note: str = "",
    ) -> HTMLResponse:
        found = values_of(request).finding_list(user_of(request), year)
        return render(
            request,
            "findings.html",
            status_code,
            year=year,
            found=found,
            show_hidden=show_hidden,
            notice=notice,
            error=error,
            note=note,
        )

    @app.post("/befunde/ausblenden")
    def dismiss_finding(  # pyright: ignore[reportUnusedFunction]
        request: Request, fields: Annotated[dict[str, str], Depends(form_fields)]
    ) -> Response:
        year = _required_year(fields)
        user = user_of(request)
        identity = (fields.get("kind", ""), fields.get("target", ""))
        found = values_of(request).finding_list(user, year)
        finding = next(
            (
                f
                for f in found.visible
                if f.identity == identity and f.fingerprint == fields.get("fingerprint")
            ),
            None,
        )
        if finding is None:
            return _findings_page(
                request,
                year,
                status_code=409,
                notice="Der Befund hat sich inzwischen geändert oder besteht nicht mehr.",
            )
        note = fields.get("note", "")
        try:
            result = dismiss(store_of(request), user, finding, note, datetime.date.today())
        except NoteMissing:
            return _findings_page(request, year, status_code=422, error=identity, note=note)
        if not isinstance(result, Applied):
            reasons = " ".join(result.reasons.values())
            return _findings_page(request, year, status_code=409, notice=reasons)
        return RedirectResponse(f"/befunde?year={year}", status_code=303)

    @app.post("/befunde/einblenden")
    def undismiss_finding(  # pyright: ignore[reportUnusedFunction]
        request: Request, fields: Annotated[dict[str, str], Depends(form_fields)]
    ) -> Response:
        year = _required_year(fields)
        result = undismiss(store_of(request), user_of(request), fields.get("id", ""))
        if result is None:
            raise HTTPException(404)
        if not isinstance(result, Applied):
            reasons = " ".join(result.reasons.values())
            return _findings_page(request, year, status_code=409, notice=reasons)
        return RedirectResponse(f"/befunde?year={year}&ausgeblendet=1", status_code=303)

    return app
