from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import moarcoal.app
from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES
from moarcoal.modules.tax_year.structure import form_pages
from moarcoal.storage import PersonalDetails, Put

_create_app = moarcoal.app.create_app


def create_app_with_user(*args: Any, with_user: bool = True, **kwargs: Any) -> FastAPI:
    """`create_app`, aber der Nutzer hat schon Angaben zur Person (Max Mustermann, ohne
    Aussteller), damit die Seiten nicht auf die Startseite umleiten. `with_user=False` lässt den
    Nutzer ungeanlegt (Tests der Startseite)."""
    app = _create_app(*args, **kwargs)
    store = app.state.store
    if with_user and not any(
        d.owner == app.state.user for d in store.state().of_kind(PersonalDetails)
    ):
        details = PersonalDetails(owner=app.state.user, first_name="Max", last_name="Mustermann")
        store.apply([Put(details)])
    return app


# Die Testmodule holen `create_app` per `from moarcoal.app import create_app`; conftest.py wird
# zuerst geladen, sie bekommen also diese Fassung.
moarcoal.app.create_app = create_app_with_user


@pytest.fixture
def anlage_n_text() -> Callable[[httpx.Client], str]:
    """Der Text aller Unterseiten der Anlage N 2025, hintereinander."""

    def read(http: httpx.Client) -> str:
        pages = form_pages(STRUCTURES[2025], FORMS[2025])
        return "".join(http.get(f"/steuerjahr/anlage-n/2025/{p.slug}").text for p in pages)

    return read
