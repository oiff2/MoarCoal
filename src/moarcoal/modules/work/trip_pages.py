"""Seite Dienstreisen je Steuerjahr: eine Tabelle, ein Vorgang; vollständig bestätigen."""

import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.modules.work.entries import (
    MAX_YEAR,
    MIN_YEAR,
    MODULE_KEY,
    trips_fingerprint,
)
from moarcoal.modules.work.germany_map import germany_map
from moarcoal.modules.work.places import (
    Place,
    PlaceError,
    forget_changes,
    hide_changes,
    locate_changes,
    place_uses,
)
from moarcoal.modules.work.trip_reading import statements, take_over_changes
from moarcoal.modules.work.trip_view import (
    PlaceSearchView,
    confirmations_of,
    places_of,
    trips_context,
    trips_of,
)
from moarcoal.modules.work.trips import (
    TripRow,
    TripTableError,
    confirm_changes,
    current_confirmation,
    plan_changes,
    rows_from_form,
)
from moarcoal.place_search import PlaceSearch, PlaceSearchError
from moarcoal.proposals import proposals_of
from moarcoal.storage import Applied, Change, Delete, Proposal, entry_checksum
from moarcoal.web import form_fields, module_state, render, store_of, user_of

router = APIRouter(prefix="/arbeit/dienstreisen")


def _year(year: int) -> int:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise HTTPException(404)
    return year


def _page(
    request: Request,
    year: int,
    *,
    rows: list[TripRow] | None = None,
    error: str = "",
    status_code: int = 200,
    problems: dict[int, str] | None = None,
    search: PlaceSearchView | None = None,
) -> HTMLResponse:
    context = trips_context(request, year, rows=rows, error=error, problems=problems, search=search)
    return render(request, "work/trips.html", status_code, **context)


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
        changes = plan_changes(rows, year, user_of(request), trips_of(request, year))
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
    trips = trips_of(request, year)
    if fields.get("stand", "") != trips_fingerprint(trips):
        error = (
            "Die Dienstreisen haben sich inzwischen geändert; bitte prüfen und erneut bestätigen."
        )
        return _page(request, year, error=error, status_code=409)
    changes = confirm_changes(
        confirmations_of(request, year), trips, year, user_of(request), datetime.date.today()
    )
    return _apply(request, year, changes)


@router.post("/{year}/vollstaendig/aufheben")
def withdraw(request: Request, year: int) -> Response:
    year = _year(year)
    confirmation = current_confirmation(confirmations_of(request, year), trips_of(request, year))
    if confirmation is None:
        return RedirectResponse(f"/arbeit/dienstreisen/{year}", status_code=303)
    return _apply(request, year, [Delete(confirmation.address, entry_checksum(confirmation))])


def _latest_proposal(request: Request, year: int, proposal_id: str) -> Proposal:
    """Der neueste Vorschlag zu einer Reiseaufstellung des Jahrs, sonst 404."""
    for document in statements(module_state(request, MODULE_KEY).documents(), year):
        history = proposals_of(store_of(request).state(), document)
        if history and history[-1].id == proposal_id:
            return history[-1]
    raise HTTPException(404)


@router.post("/{year}/vorschlag/{proposal_id}/uebernehmen")
def take_over(
    request: Request,
    year: int,
    proposal_id: str,
    fields: Annotated[dict[str, str], Depends(form_fields)],
) -> Response:
    """Die gewählten Reisen übernehmen: Dienstreisen und Bestätigung der Felder in einem Vorgang."""
    year = _year(year)
    proposal = _latest_proposal(request, year, proposal_id)
    selected = {
        int(name.removeprefix("nimm-"))
        for name, value in fields.items()
        if name.startswith("nimm-") and name.removeprefix("nimm-").isdigit() and value == "ja"
    }
    changes, problems = take_over_changes(
        proposal,
        year,
        selected,
        user_of(request),
        trips_of(request, year),
        fields.get("pruefsumme", ""),
    )
    if not changes:
        error = "" if problems else "Keine Reise gewählt."
        return _page(request, year, error=error, problems=problems, status_code=422)
    return _apply(request, year, changes)


@router.post("/{year}/vorschlag/{proposal_id}/loeschen")
def delete_proposal(
    request: Request,
    year: int,
    proposal_id: str,
    fields: Annotated[dict[str, str], Depends(form_fields)],
) -> Response:
    """Den ganzen Vorschlag löschen (die Dienstreisen bleiben, wie sie sind)."""
    year = _year(year)
    proposal = _latest_proposal(request, year, proposal_id)
    return _apply(request, year, [Delete(proposal.address, fields.get("pruefsumme", ""))])


# --- Karte: die Lage eines Orts nur nach ausdrücklichem Klick suchen (ADR 0008) ------------------


def _known_place(request: Request, year: int, name: str) -> str:
    """Der Ortsname, wenn eine Reise des Jahrs ihn nennt, sonst 404."""
    name = name.strip()
    if name not in {use.name for use in place_uses(trips_of(request, year))}:
        raise HTTPException(404)
    return name


def _stored(request: Request, name: str) -> Place | None:
    return next((p for p in places_of(request) if p.name == name), None)


@router.post("/{year}/orte/suche")
def search_place(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    """Ortssuche: nur der getippte Text geht hinaus, nur auf diese Anfrage; nichts gespeichert."""
    year = _year(year)
    name = _known_place(request, year, fields.get("ort", ""))
    text = fields.get("suche", "").strip()
    if not text:
        view = PlaceSearchView(name, text, [], "Bitte einen Suchbegriff eingeben.")
        return _page(request, year, search=view, status_code=422)
    search: PlaceSearch = request.app.state.place_search
    try:
        hits = search.search(text)
    except PlaceSearchError as error:
        return _page(
            request, year, search=PlaceSearchView(name, text, [], str(error)), status_code=502
        )
    message = "" if hits else f"Kein Treffer in Deutschland für „{text}“."
    return _page(request, year, search=PlaceSearchView(name, text, hits, message))


@router.post("/{year}/orte/lage")
def set_place_location(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    """Den gewählten Treffer als Lage des Orts speichern (für alle Jahre)."""
    year = _year(year)
    name = _known_place(request, year, fields.get("ort", ""))
    try:
        latitude, longitude = float(fields.get("breite", "")), float(fields.get("laenge", ""))
        changes = locate_changes(
            user_of(request),
            name,
            _stored(request, name),
            latitude,
            longitude,
            fields.get("name", ""),
            germany_map(),
        )
    except (ValueError, PlaceError) as error:
        raise HTTPException(400, str(error) or "Breite und Länge sind keine Zahlen.") from error
    return _apply(request, year, changes)


@router.post("/{year}/orte/ausblenden")
def hide_place(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    year = _year(year)
    name = _known_place(request, year, fields.get("ort", ""))
    return _apply(request, year, hide_changes(user_of(request), name, _stored(request, name)))


@router.post("/{year}/orte/vergessen")
def forget_place(
    request: Request, year: int, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    year = _year(year)
    name = _known_place(request, year, fields.get("ort", ""))
    changes = forget_changes(_stored(request, name))
    if not changes:
        return RedirectResponse(f"/arbeit/dienstreisen/{year}", status_code=303)
    return _apply(request, year, changes)
