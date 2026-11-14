"""Seite Dienstreisen je Steuerjahr: eine Tabelle, ein Vorgang; vollständig bestätigen."""

import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.modules.work.entries import (
    MAX_YEAR,
    MIN_YEAR,
    BusinessTrip,
    TripsConfirmation,
    trips_fingerprint,
)
from moarcoal.modules.work.pages import MODULE_KEY
from moarcoal.modules.work.trips import (
    KM_RATES,
    TripRow,
    TripTableError,
    confirm_changes,
    current_confirmation,
    place_prefill,
    plan_changes,
    rows_from_form,
    sorted_trips,
)
from moarcoal.modules.work.values import TRAVEL_FARE, TRAVEL_TOTAL
from moarcoal.storage import Applied, Change, Delete, entry_checksum
from moarcoal.values.model import Period
from moarcoal.web import form_fields, module_state, render, store_of, user_of, values_of

router = APIRouter(prefix="/arbeit/dienstreisen")


def _year(year: int) -> int:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise HTTPException(404)
    return year


def _trips(request: Request, year: int) -> list[BusinessTrip]:
    state = module_state(request, MODULE_KEY)
    return sorted_trips([t for t in state.all(BusinessTrip) if t.year == year])


def _confirmations(request: Request, year: int) -> list[TripsConfirmation]:
    state = module_state(request, MODULE_KEY)
    return [c for c in state.all(TripsConfirmation) if c.year == year]


def _page(
    request: Request,
    year: int,
    *,
    rows: list[TripRow] | None = None,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    trips = _trips(request, year)
    confirmations = _confirmations(request, year)
    rate = KM_RATES.get(year)
    if rows is None:
        rows = [TripRow.from_trip(t, rate) for t in trips]
        rows.append(TripRow(places=place_prefill(trips)))
    period = Period.year(year)
    values = values_of(request)
    user = user_of(request)
    return render(
        request,
        "work/trips.html",
        status_code,
        year=year,
        rows=rows,
        error=error,
        trip_count=len(trips),
        total_km=sum(t.distance_km for t in trips),
        rate=rate,
        confirmation=current_confirmation(confirmations, trips),
        stand=trips_fingerprint(trips),
        fare=values.get(TRAVEL_FARE, user, period),
        total=values.get(TRAVEL_TOTAL, user, period),
        min_date=f"{year}-01-01",
        max_date=f"{year}-12-31",
    )


def _apply(request: Request, year: int, changes: Sequence[Change]) -> Response:
    result = store_of(request).apply(changes)
    if isinstance(result, Applied):
        return RedirectResponse(f"/arbeit/dienstreisen/{year}", status_code=303)
    return _page(request, year, error=" ".join(result.reasons.values()), status_code=409)


@router.get("/{year}", response_class=HTMLResponse)
def show(request: Request, year: int) -> HTMLResponse:
    return _page(request, _year(year))


@router.post("/{year}")
def save(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    year = _year(year)
    rows = rows_from_form(fields)
    try:
        changes = plan_changes(rows, year, user_of(request), _trips(request, year))
    except TripTableError as error:
        return _page(request, year, rows=rows, error=str(error), status_code=422)
    if not changes:
        return RedirectResponse(f"/arbeit/dienstreisen/{year}", status_code=303)
    return _apply(request, year, changes)


@router.post("/{year}/vollstaendig")
def confirm(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    year = _year(year)
    trips = _trips(request, year)
    if fields.get("stand", "") != trips_fingerprint(trips):
        error = (
            "Die Dienstreisen haben sich inzwischen geändert; bitte prüfen und erneut bestätigen."
        )
        return _page(request, year, error=error, status_code=409)
    changes = confirm_changes(
        _confirmations(request, year), trips, year, user_of(request), datetime.date.today()
    )
    return _apply(request, year, changes)


@router.post("/{year}/vollstaendig/aufheben")
def withdraw(request: Request, year: int) -> Response:
    year = _year(year)
    confirmation = current_confirmation(_confirmations(request, year), _trips(request, year))
    if confirmation is None:
        return RedirectResponse(f"/arbeit/dienstreisen/{year}", status_code=303)
    return _apply(request, year, [Delete(confirmation.address, entry_checksum(confirmation))])
