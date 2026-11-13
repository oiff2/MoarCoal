"""Seite „Belege“, Reiter Ablage: die Ablageorte als Baum, Dateien aufnehmen oder ausblenden."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import IntakeRejected, take_in
from moarcoal.expected_documents import expected_name, pending_for
from moarcoal.incoming import (
    STANDS,
    ablage_rows,
    ablage_tree,
    all_site_files,
    hidden_files,
    hidden_section,
    hide_file,
    incoming_files,
    next_open,
    show_file,
)
from moarcoal.issuer_field import resolve_issuer
from moarcoal.prefill import Prefill, prefill_from_name
from moarcoal.previews import file_response, preview_kind
from moarcoal.storage import (
    Applied,
    Document,
    ExpectedDocument,
    HiddenFile,
    Issuer,
    SiteFile,
    entry_checksum,
)
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
    selected: str = "",
) -> HTMLResponse:
    """`selected` ist die SHA-256 der gewählten Datei; `errors` und `values` gehören zu ihr
    (Formular rechts) und bleiben dort stehen."""
    store = store_of(request)
    state = store.state()
    rows = ablage_rows(all_site_files(store), state, user_of(request))
    chosen = next((r for r in rows if r.file.sha256 == selected), None)
    kinds = document_kinds(request)
    # Vorbelegen nur für eine offene Datei und nur, solange keine abgewiesene Eingabe dasteht
    suggestion = (
        prefill_from_name(state, kinds.values(), chosen.file.path)
        if chosen and chosen.document is None and not values
        else Prefill()
    )
    # Hinweis nur bei passender Art und Jahr (aus dem Namen) und nur für eine offene Datei
    would_fulfil: list[tuple[str, str]] = []
    if suggestion.kind and suggestion.year:
        user = user_of(request)
        titles = {k: v.title for k, v in kinds.items()}
        would_fulfil = [
            (e.id, expected_name(e, titles))
            for e in pending_for(
                [d for d in state.of_kind(Document) if d.owner == user],
                [e for e in state.of_kind(ExpectedDocument) if e.owner == user],
                suggestion.kind,
                suggestion.year,
            )
        ]
    return render(
        request,
        "belege.html",
        status_code,
        tree=ablage_tree(rows, store.site_names(), stand),
        selected=chosen,
        preview_kind=chosen and preview_kind(chosen.file.path),
        preview_url=chosen
        and (
            f"/dokumente/{chosen.document.id}/datei"
            if chosen.document
            else f"/belege/datei/{chosen.file.sha256}"
        ),
        suggestion=suggestion,
        would_fulfil=would_fulfil,
        stand=stand,
        stands=STANDS,
        kinds=list(kinds.values()),
        hidden=[(h, entry_checksum(h)) for h in hidden_section(hidden_files(state), rows)],
        sites=store.site_names(),
        issuer_names={i.id: i.name for i in state.of_kind(Issuer)},
        default_year=DEFAULT_YEAR,
        notice=notice,
        errors=errors or {},
        values=values or {},
    )


def _find(request: Request, sha256: str) -> SiteFile | None:
    return next((f for f in _waiting(request) if f.sha256 == sha256), None)


def _after(request: Request, sha256: str) -> RedirectResponse | None:
    """Weiter zur nächsten offenen Datei nach `sha256`; ohne weitere `None`."""
    store = store_of(request)
    rows = ablage_rows(all_site_files(store), store.state(), user_of(request))
    following = next_open(ablage_tree(rows, store.site_names(), "offen"), sha256)
    if following is None:
        return None
    return RedirectResponse(f"/belege?datei={following}", status_code=303)


@router.get("", response_class=HTMLResponse)
def index(request: Request, stand: str = "offen", datei: str = "") -> HTMLResponse:
    return _page(request, stand=stand if stand in STANDS else "offen", selected=datei)


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
    file = _find(request, sha256)
    if file is None:
        return _page(request, 409, "Die Datei ist nicht mehr im Eingang.")

    following = _after(request, sha256)

    def rejected(*reasons: str) -> Response:
        return _page(
            request,
            422,
            errors={sha256: list(reasons)},
            values={"sha256": sha256, **fields},
            selected=sha256,
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
    chosen = resolve_issuer(store_of(request).state(), fields)
    if isinstance(chosen, str):
        return rejected(chosen)
    result = take_in(
        store_of(request),
        kinds,
        user_of(request),
        file.site,
        file.path,
        kind.key,
        year,
        values_on=lambda state: values_on(request, state),
        issuer=chosen.address,
        issuer_changes=chosen.changes,
    )
    if isinstance(result, IntakeRejected):
        return rejected(*result.reasons)
    modules = request.app.state.modules
    target = next((url for e in result.entries if (url := entry_url(modules, e.address))), None)
    if kind.extraction_template is not None:
        target = f"/dokumente/{result.document.id}"  # dort liest der Nutzer das Dokument aus
    elif following is not None:
        return following
    return RedirectResponse(target or "/belege", status_code=303)


@router.post("/ausblenden")
def hide(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
    file = _find(request, fields.get("sha256", ""))
    if file is None:
        return _page(request, 409, "Die Datei ist nicht mehr im Eingang.")
    following = _after(request, file.sha256)
    result = hide_file(store_of(request), file, fields.get("note", ""))
    if not isinstance(result, Applied):
        return _page(request, 409, " ".join(result.reasons.values()), selected=file.sha256)
    return following or RedirectResponse("/belege", status_code=303)


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
