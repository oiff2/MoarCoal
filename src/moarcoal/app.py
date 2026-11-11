"""App-Fabrik: FastAPI mit Jinja2-Vorlagen, lokal ausgeliefertem htmx und den Modulen."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.modules import MODULES
from moarcoal.registration import ModuleRegistration
from moarcoal.security import SecurityMiddleware
from moarcoal.storage import open_store
from moarcoal.web import entry_url, format_amount, format_eur, render, user_of, values_of

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
# Durchstich: ein Nutzer, die Nutzerliste kommt später; der Anzeigename ist erfunden.
DEFAULT_USER = "ich"
DEFAULT_USER_NAME = "Max Mustermann"


def create_app(
    port: int,
    data_dir: Path,
    modules: Sequence[ModuleRegistration] = MODULES,
    user: str = DEFAULT_USER,
    user_name: str = DEFAULT_USER_NAME,
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
    app.state.store = open_store(data_dir, [kind for module in modules for kind in module.kinds])
    for module in modules:
        app.include_router(module.router)

    @app.get("/", response_class=HTMLResponse)
    def start(request: Request) -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return render(request, "start.html")

    @app.get("/befunde", response_class=HTMLResponse)
    def findings(request: Request, year: int = DEFAULT_YEAR) -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        found = values_of(request).finding_list(user_of(request), year)
        return render(request, "findings.html", year=year, findings=found)

    return app
