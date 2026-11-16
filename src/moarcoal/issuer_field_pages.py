"""Route des Aussteller-Felds: Suchergebnisse als Auswahlliste (`issuer_field.py`)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from moarcoal.issuer_field import holder_of_name, issuer_at, last_issuer, search_issuers
from moarcoal.web import render, store_of, user_of

router = APIRouter()

MAX_HITS = 8


@router.get("/aussteller-suche", response_class=HTMLResponse)
def search(
    request: Request,
    issuer_text: str = "",
    issuer_choice: str = "",
    kind: str = "",
    default: str = "",
    clear: str = "",
) -> HTMLResponse:
    """Ergebnisse der Suche als Auswahlliste (Vorlage `_issuer_choices.html`); schreibt nie.

    Ohne Text und ohne Auswahl gilt `default` (Kennung), sonst der zuletzt für `kind` verwendete;
    das entfällt mit `clear` (der Nutzer hat „ändern“ gedrückt).
    """
    state = store_of(request).state()
    text = issuer_text.strip()
    selected = issuer_choice
    if not text and not selected and not clear:
        preset = issuer_at(state, default) or last_issuer(state, user_of(request), kind or None)
        selected = f"id:{preset.id}" if preset is not None else ""
    return render(
        request,
        "_issuer_choices.html",
        text=text,
        hits=search_issuers(state, text)[:MAX_HITS],
        exact=holder_of_name(state, text) is not None,
        selected=selected,
        chosen=issuer_at(state, selected.partition(":")[2]),
    )
