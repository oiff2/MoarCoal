"""Seite „Belege <Jahr>“: neue Dateien, Erwartete Belege und aufgenommene Belege des gewählten
Jahrs, dazu Aufnehmen und Ausblenden der Dateien (Abschnitt Neu)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.documents import IntakeRejected, read_document_choice, take_in
from moarcoal.incoming import (
    all_site_files,
    folder_path_error,
    hide_file,
    hide_folder,
    incoming_files,
    unhide,
)
from moarcoal.prefill import Prefill, prefill_from_name
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import (
    Applied,
    Document,
    HiddenFile,
    HiddenFolder,
    Issuer,
    SiteFile,
    entry_checksum,
)
from moarcoal.web.helpers import (
    document_kinds,
    entry_url,
    form_fields,
    global_year,
    rejection_text,
    render,
    store_of,
    user_of,
    values_on,
)
from moarcoal.web.links import document_file_url, document_url, site_file_url, site_url
from moarcoal.web.previews import file_response, preview_kind
from moarcoal.web.site_view import (
    expected_rows,
    new_section,
    next_open,
    year_documents,
)

router = APIRouter(prefix="/belege")
moved_router = APIRouter()  # alte Adressen /eingang…

type Fields = dict[str, str]

GONE = "Die Datei ist nicht mehr in der Ablage."
"""Meldung, wenn die gewählte Datei nicht mehr offen ist (aufgenommen, ausgeblendet, fort)."""


def document_detail(
    request: Request, document: Document, issuer_text: str = "", year: str = ""
) -> dict[str, Any]:
    """Alles, was `documents/_detail.html` für den Kopf eines Dokuments braucht. `issuer_text` und
    `year` stellen eine abgewiesene Eingabe wieder her."""
    store = store_of(request)
    state = store.state()
    kinds = document_kinds(request)
    kind = kinds.get(document.document_kind or "")
    return {
        "document": document,
        "issuer": state.get(document.issuer) if document.issuer else None,
        "issuer_text": issuer_text,
        "year": year,
        "kinds": list(kinds.values()),
        "references": store.references_to(document.address),
        "bound": store.references_to(document.address, with_derived=True),
        "checksum": entry_checksum(document),
        "labels": store.kind_labels(),
        "default_year": global_year(request),
        "kind": kind,
        "template": template_of(kinds, document),
        "proposal": latest_proposal(state, document),
    }


def _open_file(request: Request, sha256: str) -> SiteFile | None:
    """Die Datei mit diesem SHA-256 im Eingang des Nutzers (aller Ablageorte)."""
    store = store_of(request)
    files = incoming_files(all_site_files(store), store.state(), user_of(request))
    return next((f for f in files if f.sha256 == sha256), None)


def belege_page(
    request: Request,
    status_code: int = 200,
    notice: str = "",
    *,
    selected: str = "",
    document: Document | None = None,
    existing: Document | None = None,
    rejected: IntakeRejected | None = None,
    values: Fields | None = None,
    issuer_text: str = "",
    year_text: str = "",
    expected_errors: list[str] | None = None,
    expected_values: Fields | None = None,
) -> HTMLResponse:
    """Die Seite des gewählten Jahrs. Rechts steht, was gewählt ist: eine Datei des Eingangs oder
    eine ausgeblendete (`selected`: SHA-256) oder ein Dokument (`document`). `rejected`, `values`
    und `notice` gehören zu der Wahl und bleiben dort stehen (`existing` ist das vorhandene Dokument
    bei „Existiert bereits“; `issuer_text` und `year_text` stellen die abgewiesene Eingabe eines
    Dokuments wieder her); `expected_errors` und `expected_values`
    gehören zum Formular für einen Erwarteten Beleg."""
    store = store_of(request)
    state = store.state()
    user = user_of(request)
    year = global_year(request)
    files = all_site_files(store)
    open_files = incoming_files(files, state, user)
    new = new_section(files, store.sites, state, user, year)
    kinds = document_kinds(request)
    chosen = next((f for f in open_files if f.sha256 == selected), None)
    hidden_chosen = None if chosen else new.hidden_file(selected)
    # Vorbelegen nur für eine offene Datei und nur, solange keine abgewiesene Eingabe dasteht
    suggestion = (
        prefill_from_name(state, kinds.values(), chosen.path)
        if chosen and not values
        else Prefill()
    )
    if chosen:
        preview_url, preview_path = site_file_url(chosen.sha256), chosen.path
    elif hidden_chosen:
        preview_url, preview_path = hidden_chosen.preview_url, hidden_chosen.path
    elif document:
        preview_url, preview_path = document_file_url(document.id), document.path
    else:
        preview_url = preview_path = ""
    return render(
        request,
        "belege.html",
        status_code,
        open_files=len(open_files),
        year=year,
        new=new,
        expected=expected_rows(state, user, year, kinds),
        expected_kinds={k.key: k for k in kinds.values() if k.has_period},
        expected_errors=expected_errors or [],
        expected_values=expected_values or {"start_year": str(year)},
        taken_in=year_documents(state, store.sites, kinds, user, year),
        selected=chosen,
        selected_document=document,
        detail=document_detail(request, document, issuer_text, year_text) if document else None,
        selected_hidden=hidden_chosen,
        preview_kind=preview_kind(preview_path) if preview_url else None,
        preview_url=preview_url,
        suggestion=suggestion,
        kinds=list(kinds.values()),
        issuer_names={i.id: i.name for i in state.of_kind(Issuer)},
        default_year=year,
        notice=notice,
        errors={selected: list(rejected.reasons)} if rejected else {},
        values=values or {},
        existing=existing or (rejected.existing if rejected else None),
        configured=bool(store.sites.names()),
    )


def _after(request: Request, sha256: str) -> RedirectResponse | None:
    """Weiter zur nächsten Datei des Abschnitts Neu nach `sha256`; ohne weitere `None`."""
    store = store_of(request)
    new = new_section(
        all_site_files(store), store.sites, store.state(), user_of(request), global_year(request)
    )
    following = next_open([f.file.sha256 for f in new.files()], sha256)
    if following is None:
        return None
    return RedirectResponse(f"{site_url()}?datei={following}", status_code=303)


@router.get("", response_class=HTMLResponse)
def index(request: Request, datei: str = "", dokument: str = "") -> HTMLResponse:
    state, user = store_of(request).state(), user_of(request)
    document = next(
        (d for d in state.of_kind(Document) if d.id == dokument and d.owner == user), None
    )
    return belege_page(request, selected=datei, document=document)


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
    file = _open_file(request, sha256)
    if file is None:
        return belege_page(request, 409, GONE)

    following = _after(request, sha256)
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
            label=choice.label,
        )
    )
    if isinstance(result, IntakeRejected):
        return belege_page(
            request,
            422,
            selected=sha256,
            rejected=result,
            values={"sha256": sha256, **fields},
        )
    modules = request.app.state.modules
    target = next((url for e in result.entries if (url := entry_url(modules, e.address))), None)
    if template_of(kinds, result.document) is not None:
        # auf der Seite des Dokuments liest der Nutzer es aus
        target = document_url(result.document.id)
    elif following is not None:
        return following
    return RedirectResponse(target or site_url(), status_code=303)


@router.post("/ausblenden")
def hide(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    file = _open_file(request, fields.get("sha256", ""))
    if file is None:
        return belege_page(request, 409, GONE)
    following = _after(request, file.sha256)
    result = hide_file(store_of(request), file, fields.get("note", ""))
    if not isinstance(result, Applied):
        return belege_page(request, 409, rejection_text(result), selected=file.sha256)
    return following or RedirectResponse(site_url(), status_code=303)


@router.post("/ausblenden-direkt")
def hide_directly(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    """Ein Klick in der Zeile: eine offene Datei (`sha256`) oder ein Ordner (`site` und `path`)."""
    store = store_of(request)
    back = RedirectResponse(site_url(), 303)
    if "sha256" in fields:
        file = _open_file(request, fields["sha256"])
        if file is None:
            return belege_page(request, 409, GONE)
        result = hide_file(store, file, "")
    else:
        site, path = fields.get("site", ""), fields.get("path", "")
        if site not in store.sites.names():
            return belege_page(request, 409, f"Unbekannter Ablageort {site!r}.")
        error = folder_path_error(all_site_files(store), site, path)
        if error:
            return belege_page(request, 409, error)
        result = hide_folder(store, store.state(), site, path)
    if result is not None and not isinstance(result, Applied):
        return belege_page(request, 409, rejection_text(result))
    return back


def _unhide(request: Request, hidden: HiddenFile | HiddenFolder | None, checksum: str) -> Response:
    if hidden is None:
        return belege_page(request, 409, "Die Ausblendung gibt es nicht mehr.")
    result = unhide(store_of(request), hidden, checksum)
    if not isinstance(result, Applied):
        changed = "Die Ausblendung wurde inzwischen geändert. Bitte neu prüfen."
        return belege_page(request, 409, changed)
    return RedirectResponse(site_url(), status_code=303)


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


@router.get("/dokumente")
def moved_documents() -> RedirectResponse:
    """Die Dokumente sind der Abschnitt Aufgenommene Belege der Seite."""
    return RedirectResponse(site_url(), status_code=308)


@moved_router.api_route("/erwartete-belege", methods=["GET", "POST"])
@moved_router.api_route("/erwartete-belege/{rest:path}", methods=["GET", "POST"])
def moved_expected(rest: str = "") -> RedirectResponse:
    """Die Erwarteten Belege sind ein Abschnitt der Belege-Seite; 308 behält Methode und Formular
    bei."""
    return RedirectResponse(f"/belege/erwartet/{rest}".rstrip("/"), status_code=308)


@moved_router.api_route("/eingang", methods=["GET", "POST"])
@moved_router.api_route("/eingang/{rest:path}", methods=["GET", "POST"])
def moved(rest: str = "") -> RedirectResponse:
    """Der Eingang ist der Abschnitt Neu der Belege-Seite; 308 behält Methode und Formular bei."""
    return RedirectResponse(f"/belege/{rest}".rstrip("/"), status_code=308)
