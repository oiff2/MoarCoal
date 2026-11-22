"""Testhilfe: `make_app` baut die App wie `create_app`, aber mit angelegtem Nutzer."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from moarcoal.storage import PersonalDetails, Put
from moarcoal.web.app import create_app


def make_app(*args: Any, with_user: bool = True, **kwargs: Any) -> FastAPI:
    """`create_app`, aber der Nutzer hat schon Angaben zur Person (Max Mustermann, ohne
    Aussteller), damit die Seiten nicht auf die Startseite umleiten. `with_user=False` lässt den
    Nutzer ungeanlegt (Tests der Startseite)."""
    app = create_app(*args, **kwargs)
    store = app.state.store
    if with_user and not any(
        d.owner == app.state.user for d in store.state().of_kind(PersonalDetails)
    ):
        details = PersonalDetails(owner=app.state.user, first_name="Max", last_name="Mustermann")
        store.apply([Put(details)])
    return app


STATIC = Path(__file__).parents[1] / "src" / "moarcoal" / "static"


def stylesheet() -> str:
    """Die drei Stylesheets in der Reihenfolge, in der die Seite sie einbindet."""
    return "".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("tokens.css", "bausteine.css", "seiten.css")
    )
