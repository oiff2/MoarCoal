"""Seite „Belege“, Reiter Ablage: die Ablageorte als Baum, Dateien aufnehmen oder ausblenden."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import IntakeRejected, take_in
from moarcoal.incoming import (
    STANDS,
    ablage_rows,
    ablage_tree,
    all_site_files,
    hidden_files,
    hidden_section,
    hide_file,
    incoming_files,
    show_file,
)
from moarcoal.storage import Applied, HiddenFile, SiteFile, entry_checksum
from moarcoal.web import (
    document_kinds,
    entry_url,
    form_fields,
    render,
    store_of,
    user_of,
    values_on,
)

router = APIRouter(prefix="/belege")
moved_router = APIRouter()  # alte Adressen /eingang…

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
    stand: str = "offen",
) -> HTMLResponse:
    """`errors` und `values` gehören zur Zeile der Datei (SHA-256) und bleiben dort stehen."""
    store = store_of(request)
    state = store.state()
    rows = ablage_rows(all_site_files(store), state, user_of(request))
    return render(
        request,
        "belege.html",
        status_code,
        tree=ablage_tree(rows, store.site_names(), stand),
        stand=stand,
        stands=STANDS,
        kinds=list(document_kinds(request).values()),
        hidden=[(h, entry_checksum(h)) for h in hidden_section(hidden_files(state), rows)],
        sites=store.site_names(),
        default_year=DEFAULT_YEAR,
        notice=notice,
        errors=errors or {},
        values=values or {},
    )


def _find(request: Request, sha256: str) -> SiteFile | None:
    return next((f for f in _waiting(request) if f.sha256 == sha256), None)


@router.get("", response_class=HTMLResponse)
def index(request: Request, stand: str = "offen") -> HTMLResponse:
    return _page(request, stand=stand if stand in STANDS else "offen")


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
        store_of(request),
        kinds,
        user_of(request),
        file.site,
        file.path,
        kind.key,
        year,
        values_on=lambda state: values_on(request, state),
    )
    if isinstance(result, IntakeRejected):
        return rejected(*result.reasons)
    modules = request.app.state.modules
    target = next((url for e in result.entries if (url := entry_url(modules, e.address))), None)
    if kind.extraction_template is not None:
        target = f"/dokumente/{result.document.id}"  # dort liest der Nutzer das Dokument aus
    return RedirectResponse(target or "/belege", status_code=303)


@router.post("/ausblenden")
def hide(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    file = _find(request, fields.get("sha256", ""))
    if file is None:
        return _page(request, 409, "Die Datei ist nicht mehr im Eingang.")
    result = hide_file(store_of(request), file, fields.get("note", ""))
    if not isinstance(result, Applied):
        return _page(request, 409, " ".join(result.reasons.values()))
    return RedirectResponse("/belege", status_code=303)


@router.post("/einblenden")
def show(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    sha256 = fields.get("sha256", "")
    state = store_of(request).state()
    hidden = next((h for h in state.of_kind(HiddenFile) if h.sha256 == sha256), None)
    if hidden is None:
        return _page(request, 409, "Die Ausblendung gibt es nicht mehr.")
    result = show_file(store_of(request), hidden, fields.get("checksum", ""))
    if not isinstance(result, Applied):
        return _page(request, 409, "Die Ausblendung wurde inzwischen geändert. Bitte neu prüfen.")
    return RedirectResponse("/belege", status_code=303)


@moved_router.api_route("/eingang", methods=["GET", "POST"])
@moved_router.api_route("/eingang/{rest:path}", methods=["GET", "POST"])
def moved(rest: str = "") -> RedirectResponse:
    """Der Eingang ist der Filter „offen“ der Ablage; 308 behält Methode und Formular bei."""
    return RedirectResponse(f"/belege/{rest}".rstrip("/"), status_code=308)
