"""Seite „Belege“, Reiter Ablage: die Ablageorte als Baum, Dateien aufnehmen oder ausblenden."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.document_list import document_detail, read_document_choice
from moarcoal.documents import IntakeRejected, take_in
from moarcoal.incoming import (
    IntakeFilter,
    SiteListing,
    all_site_files,
    folder_path_error,
    hide_file,
    hide_folder,
    next_open,
    site_listing,
    unhide,
)
from moarcoal.prefill import Prefill, prefill_from_name
from moarcoal.previews import file_response, preview_kind
from moarcoal.storage import Applied, HiddenFile, HiddenFolder, Issuer
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

GONE = "Die Datei ist nicht mehr in der Ablage."
"""Meldung, wenn die gewählte Datei nicht mehr offen ist (aufgenommen, ausgeblendet, fort)."""


def _listing(request: Request) -> SiteListing:
    store = store_of(request)
    return site_listing(store, store.state(), user_of(request))


def _page(
    request: Request,
    listing: SiteListing | None = None,
    status_code: int = 200,
    notice: str = "",
    *,
    intake_filter: IntakeFilter = IntakeFilter.OPEN,
    selected: str = "",
    rejected: IntakeRejected | None = None,
    values: Fields | None = None,
) -> HTMLResponse:
    """`selected` ist die SHA-256 der gewählten Datei (der Ablage oder der Ausgeblendeten);
    `rejected` und `values` gehören zu ihr (Formular rechts) und bleiben dort stehen."""
    listing = listing or _listing(request)
    store = store_of(request)
    state = store.state()
    chosen = listing.row(selected)
    hidden_chosen = listing.hidden_file(selected)
    kinds = document_kinds(request)
    # Vorbelegen nur für eine offene Datei und nur, solange keine abgewiesene Eingabe dasteht
    suggestion = (
        prefill_from_name(state, kinds.values(), chosen.file.path)
        if chosen and chosen.document is None and not values
        else Prefill()
    )
    shown = chosen or hidden_chosen
    preview_url = shown.preview_url if shown else ""
    return render(
        request,
        "belege.html",
        status_code,
        open_files=len(listing.open_files()),
        tree=listing.tree(intake_filter),
        selected=chosen,
        detail=document_detail(request, chosen.document) if chosen and chosen.document else None,
        selected_hidden=hidden_chosen,
        preview_kind=preview_kind(shown.path) if shown and preview_url else None,
        preview_url=preview_url,
        suggestion=suggestion,
        intake_filter=intake_filter,
        intake_filters=list(IntakeFilter),
        kinds=list(kinds.values()),
        hidden_files=listing.hidden_files,
        hidden_folders=listing.hidden_folders,
        sites=listing.sites,
        issuer_names={i.id: i.name for i in state.of_kind(Issuer)},
        default_year=DEFAULT_YEAR,
        notice=notice,
        errors={selected: list(rejected.reasons)} if rejected else {},
        values=values or {},
        existing=rejected.existing if rejected else None,
    )


def _after(listing: SiteListing, sha256: str) -> RedirectResponse | None:
    """Weiter zur nächsten offenen Datei nach `sha256`; ohne weitere `None`."""
    following = next_open(listing.tree(IntakeFilter.OPEN), sha256)
    if following is None:
        return None
    return RedirectResponse(f"/belege?datei={following}", status_code=303)


@router.get("", response_class=HTMLResponse)
def index(request: Request, stand: str = "offen", datei: str = "") -> HTMLResponse:
    return _page(request, intake_filter=IntakeFilter.of(stand), selected=datei)


@router.get("/datei/{sha256}")
def file(request: Request, sha256: str) -> Response:
    """Die Datei der Ablage mit diesem SHA-256 (Vorschau); unbekannter SHA-256: 404."""
    found = next((f for f in all_site_files(store_of(request)) if f.sha256 == sha256), None)
    if found is None:
        raise HTTPException(404)
    return file_response(store_of(request), found.site, found.path, found.sha256)


@router.post("/aufnehmen")
def take_in_file(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    sha256 = fields.get("sha256", "")
    listing = _listing(request)
    file = listing.open_file(sha256)
    if file is None:
        return _page(request, listing, 409, GONE)

    following = _after(listing, sha256)
    kinds = document_kinds(request)
    choice = read_document_choice(store_of(request).state(), kinds, fields)
    result = (
        choice
        if isinstance(choice, IntakeRejected)
        else take_in(
            store_of(request),
            kinds,
            user_of(request),
            file.site,
            file.path,
            choice.kind_key or "",
            choice.year,
            values_on=lambda state: values_on(request, state),
            issuer=choice.issuer.address,
            issuer_changes=choice.issuer.changes,
        )
    )
    if isinstance(result, IntakeRejected):
        return _page(
            request,
            listing,
            422,
            selected=sha256,
            rejected=result,
            values={"sha256": sha256, **fields},
        )
    modules = request.app.state.modules
    target = next((url for e in result.entries if (url := entry_url(modules, e.address))), None)
    kind = kinds.get(result.document.document_kind or "")
    if kind is not None and kind.extraction_template is not None:
        # im Reiter Dokumente liest der Nutzer das Dokument aus
        target = result.document.url
    elif following is not None:
        return following
    return RedirectResponse(target or "/belege", status_code=303)


@router.post("/ausblenden")
def hide(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    listing = _listing(request)
    file = listing.open_file(fields.get("sha256", ""))
    if file is None:
        return _page(request, listing, 409, GONE)
    following = _after(listing, file.sha256)
    result = hide_file(store_of(request), file, fields.get("note", ""))
    if not isinstance(result, Applied):
        return _page(request, listing, 409, " ".join(result.reasons.values()), selected=file.sha256)
    return following or RedirectResponse("/belege", status_code=303)


@router.post("/ausblenden-direkt")
def hide_directly(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    """Ein Klick in der Zeile: eine offene Datei (`sha256`) oder ein Ordner (`site` und `path`)."""
    store = store_of(request)
    listing = _listing(request)
    intake_filter = IntakeFilter.of(fields.get("stand", ""))
    back = RedirectResponse(f"/belege?stand={intake_filter}", 303)
    if "sha256" in fields:
        file = listing.open_file(fields["sha256"])
        if file is None:
            return _page(request, listing, 409, GONE)
        result = hide_file(store, file, "")
    else:
        site, path = fields.get("site", ""), fields.get("path", "")
        if site not in listing.sites:
            return _page(request, listing, 409, f"Unbekannter Ablageort {site!r}.")
        error = folder_path_error(listing.files, site, path)
        if error:
            return _page(request, listing, 409, error)
        result = hide_folder(store, store.state(), site, path)
    if result is not None and not isinstance(result, Applied):
        return _page(request, listing, 409, " ".join(result.reasons.values()))
    return back


def _unhide(request: Request, hidden: HiddenFile | HiddenFolder | None, checksum: str) -> Response:
    if hidden is None:
        return _page(request, None, 409, "Die Ausblendung gibt es nicht mehr.")
    result = unhide(store_of(request), hidden, checksum)
    if not isinstance(result, Applied):
        changed = "Die Ausblendung wurde inzwischen geändert. Bitte neu prüfen."
        return _page(request, None, 409, changed)
    return RedirectResponse("/belege", status_code=303)


@router.post("/einblenden-ordner")
def show_folder(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    site, path = fields.get("site", ""), fields.get("path", "")
    folders = store_of(request).state().of_kind(HiddenFolder)
    hidden = next((h for h in folders if (h.site, h.path) == (site, path)), None)
    return _unhide(request, hidden, fields.get("checksum", ""))


@router.post("/einblenden")
def show(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    sha256 = fields.get("sha256", "")
    files = store_of(request).state().of_kind(HiddenFile)
    hidden = next((h for h in files if h.sha256 == sha256), None)
    return _unhide(request, hidden, fields.get("checksum", ""))


@moved_router.api_route("/erwartete-belege", methods=["GET", "POST"])
@moved_router.api_route("/erwartete-belege/{rest:path}", methods=["GET", "POST"])
def moved_expected(rest: str = "") -> RedirectResponse:
    """Die Erwarteten Belege sind der Reiter Erwartet; 308 behält Methode und Formular bei."""
    return RedirectResponse(f"/belege/erwartet/{rest}".rstrip("/"), status_code=308)


@moved_router.api_route("/eingang", methods=["GET", "POST"])
@moved_router.api_route("/eingang/{rest:path}", methods=["GET", "POST"])
def moved(rest: str = "") -> RedirectResponse:
    """Der Eingang ist der Filter „offen“ der Ablage; 308 behält Methode und Formular bei."""
    return RedirectResponse(f"/belege/{rest}".rstrip("/"), status_code=308)
