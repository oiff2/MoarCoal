"""Testhilfe: `make_app` baut die App wie `create_app`, aber mit angelegtem Nutzer."""

from typing import Any

from fastapi import FastAPI

from moarcoal.app import create_app
from moarcoal.storage import PersonalDetails, Put


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
