"""Seite „Eingang“: neue Dateien der Ablageorte aufnehmen oder ausblenden (Spec 3.6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import IntakeRejected, take_in
from moarcoal.incoming import all_site_files, hide_file, incoming_files
from moarcoal.storage import Applied, SiteFile
from moarcoal.web import (
    document_kinds,
    entry_url,
    form_fields,
    render,
    store_of,
    user_of,
)

router = APIRouter(prefix="/eingang")

type Fields = dict[str, str]


def _waiting(request: Request) -> list[SiteFile]:
    store = store_of(request)
    return incoming_files(all_site_files(store), store.state(), user_of(request))


def _page(
    request: Request,
    status_code: int = 200,
    notice: str = "",
    errors: dict[str, list[str]] | None = None,
    values: Fields | None = None,
) -> HTMLResponse:
    """`errors` und `values` gehören zur Zeile der Datei (SHA-256) und bleiben dort stehen."""
    return render(
        request,
        "incoming.html",
        status_code,
        files=_waiting(request),
        kinds=list(document_kinds(request).values()),
        sites=store_of(request).site_names(),
        default_year=DEFAULT_YEAR,
        notice=notice,
        errors=errors or {},
        values=values or {},
    )


def _find(request: Request, sha256: str) -> SiteFile | None:
    return next((f for f in _waiting(request) if f.sha256 == sha256), None)


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _page(request)


@router.post("/aufnehmen")
def take_in_file(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    sha256 = fields.get("sha256", "")
    file = _find(request, sha256)
    if file is None:
        return _page(request, 409, "Die Datei ist nicht mehr im Eingang.")

    def rejected(*reasons: str) -> Response:
        return _page(
            request, 422, errors={sha256: list(reasons)}, values={"sha256": sha256, **fields}
        )

    kinds = document_kinds(request)
    kind = kinds.get(fields.get("kind", ""))
    if kind is None:
        return rejected("Bitte eine Dokumentart wählen.")
    year = DEFAULT_YEAR
    if kind.has_period:
        try:
            year = int(fields.get("year", "").strip())
        except ValueError:
            return rejected("Steuerjahr: ganze Zahl, z. B. 2025")
    result = take_in(
        store_of(request), kinds, user_of(request), file.site, file.path, kind.key, year
    )
    if isinstance(result, IntakeRejected):
        return rejected(*result.reasons)
    modules = request.app.state.modules
    target = next((url for e in result.entries if (url := entry_url(modules, e.address))), None)
    return RedirectResponse(target or "/eingang", status_code=303)


@router.post("/ausblenden")
def hide(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    file = _find(request, fields.get("sha256", ""))
    if file is None:
        return _page(request, 409, "Die Datei ist nicht mehr im Eingang.")
    result = hide_file(store_of(request), file, fields.get("note", ""))
    if not isinstance(result, Applied):
        return _page(request, 409, " ".join(result.reasons.values()))
    return RedirectResponse("/eingang", status_code=303)
