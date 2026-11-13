"""Das Aussteller-Feld: Suche über Name und Aliasse, Auswahl, Neu anlegen, Alias hinzufügen.

Wiederverwendbar (Vorlage `_issuer_field.html`): beim Aufnehmen und am Dokument. Die Auswahl
kommt als `issuer_choice` an (leer = kein Aussteller, `id:<Kennung>`, `new`, `alias:<Kennung>`),
der Text als `issuer_text`, das Häkchen als `issuer_private`. Anlegen und Alias sind Änderungen,
die der Aufrufer im selben Vorgang wie das Dokument schreibt.
"""

import datetime
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from moarcoal.storage import (
    COMMON_OWNER,
    Change,
    Document,
    EntryAddress,
    Issuer,
    Put,
    State,
    entry_checksum,
    issuer_with_name,
    name_key,
)
from moarcoal.web import render, store_of, user_of

router = APIRouter()

MAX_HITS = 8


@dataclass(frozen=True)
class IssuerChoice:
    """Gewählter Aussteller (oder keiner) und was dafür geschrieben werden muss."""

    address: EntryAddress | None = None
    changes: tuple[Change, ...] = ()


def _names(issuer: Issuer) -> list[str]:
    return [issuer.name, *issuer.aliases]


def search_issuers(state: State, text: str) -> list[Issuer]:
    """Aussteller, deren Name oder Alias den Text enthält oder darin vorkommt; ohne Groß-/
    Kleinschreibung, nach Name sortiert."""
    needle = name_key(text)
    if not needle:
        return []
    found = [
        i
        for i in state.of_kind(Issuer)
        if any(name_key(n) in needle or needle in name_key(n) for n in _names(i))
    ]
    return sorted(found, key=lambda i: name_key(i.name))


def holder_of_name(state: State, text: str) -> Issuer | None:
    """Der Aussteller, der den Namen schon als Name oder Alias trägt."""
    return issuer_with_name(state.of_kind(Issuer), text)


def _taken(holder: Issuer) -> str:
    return f"Duplikat zu: {holder.name}. Bitte aus der Suche wählen."


def _issuer_at(state: State, issuer_id: str) -> Issuer | None:
    found = state.get(EntryAddress(kind="Issuer", id=issuer_id)) if issuer_id.isalnum() else None
    return found if isinstance(found, Issuer) else None


def last_issuer(state: State, user: str, kind_key: str | None) -> Issuer | None:
    """Der zuletzt für die Dokumentart verwendete Aussteller (nur Oberfläche, nichts gespeichert)"""
    used = [
        d
        for d in state.of_kind(Document)
        if d.owner == user and d.document_kind == kind_key and d.issuer is not None
    ]
    if not used:
        return None
    newest = max(
        used,
        key=lambda d: (d.taken_in_at or datetime.datetime.min.replace(tzinfo=datetime.UTC), d.id),
    )
    return _issuer_at(state, newest.issuer.id) if newest.issuer else None


def resolve_issuer(state: State, fields: Mapping[str, str]) -> IssuerChoice | str:
    """Aus den Formularfeldern den Aussteller; bei einem Fehler die Meldung für den Nutzer."""
    choice = fields.get("issuer_choice", "")
    text = fields.get("issuer_text", "").strip()
    if choice == "":
        return IssuerChoice() if not text else "Bitte einen Aussteller aus der Suche wählen."
    if choice == "new":
        if not text:
            return "Bitte einen Namen für den neuen Aussteller eingeben."
        holder = holder_of_name(state, text)
        if holder is not None:
            return _taken(holder)
        private = bool(fields.get("issuer_private"))
        issuer = Issuer(owner=COMMON_OWNER, name=text, private_person=private)
        return IssuerChoice(issuer.address, (Put(issuer),))
    mode, _, issuer_id = choice.partition(":")
    existing = _issuer_at(state, issuer_id)
    if existing is None or mode not in ("id", "alias"):
        return "Der gewählte Aussteller ist nicht mehr da."
    if mode == "id":
        return IssuerChoice(existing.address)
    if not text:
        return "Bitte den weiteren Namen eingeben."
    holder = holder_of_name(state, text)
    if holder is not None:
        return IssuerChoice(existing.address) if holder.id == existing.id else _taken(holder)
    renamed = existing.model_copy(update={"aliases": (*existing.aliases, text)})
    return IssuerChoice(existing.address, (Put(renamed, entry_checksum(existing)),))


@router.get("/aussteller-suche", response_class=HTMLResponse)
def search(
    request: Request,
    issuer_text: str = "",
    issuer_choice: str = "",
    kind: str = "",
    default: str = "",
    issuer_private: str = "",
) -> HTMLResponse:
    """Ergebnisse der Suche als Auswahlliste (Vorlage `_issuer_choices.html`); schreibt nie.

    Ohne Text und ohne Auswahl gilt `default` (Kennung), sonst der zuletzt für `kind` verwendete.
    """
    state = store_of(request).state()
    text = issuer_text.strip()
    selected = issuer_choice
    if not text and not selected:
        preset = _issuer_at(state, default) or last_issuer(state, user_of(request), kind or None)
        selected = f"id:{preset.id}" if preset is not None else ""
    return render(
        request,
        "_issuer_choices.html",
        text=text,
        hits=search_issuers(state, text)[:MAX_HITS],
        exact=holder_of_name(state, text) is not None,
        selected=selected,
        private=bool(issuer_private),
        preset=_issuer_at(state, selected.partition(":")[2]),
    )
