"""Seite „Befunde“: die Befundliste eines Jahrs, Befunde ausblenden und wieder einblenden."""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import year_of
from moarcoal.dismissals import NoteMissing, dismiss, undismiss
from moarcoal.storage import Applied
from moarcoal.web.helpers import (
    finding_list_of,
    form_fields,
    global_year,
    rejection_text,
    render,
    store_of,
    user_of,
    values_of,
)
from moarcoal.web.links import findings_url, site_return_url

router = APIRouter()


def _required_year(fields: dict[str, str]) -> int:
    year = year_of(fields.get("year", ""))
    if year is None:
        raise HTTPException(422, "Jahr fehlt oder ist keine Zahl.")
    return year


@router.get("/befunde", response_class=HTMLResponse)
def findings(request: Request, year: int | None = None, ausgeblendet: int = 0) -> HTMLResponse:
    chosen = global_year(request) if year is None else year
    return _findings_page(request, chosen, show_hidden=bool(ausgeblendet))


def _findings_page(
    request: Request,
    year: int,
    show_hidden: bool = False,
    status_code: int = 200,
    notice: str = "",
    error: tuple[str, str] | None = None,
    note: str = "",
) -> HTMLResponse:
    found = finding_list_of(request, year)
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


@router.post("/befunde/ausblenden")
def dismiss_finding(
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
        reasons = rejection_text(result)
        return _findings_page(request, year, status_code=409, notice=reasons)
    back = site_return_url(fields.get("zurueck", ""))
    return RedirectResponse(back or findings_url(year), status_code=303)


@router.post("/befunde/einblenden")
def undismiss_finding(
    request: Request, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    year = _required_year(fields)
    result = undismiss(store_of(request), user_of(request), fields.get("id", ""))
    if result is None:
        raise HTTPException(404)
    if not isinstance(result, Applied):
        reasons = rejection_text(result)
        return _findings_page(request, year, status_code=409, notice=reasons)
    return RedirectResponse(findings_url(year, hidden=True), status_code=303)
