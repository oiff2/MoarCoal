"""Seite „Belege“, Reiter Dokumente: alle aufgenommenen Dokumente mit Filter und Suche.

Der Zustand eines Dokuments wird bei jeder Anfrage abgeleitet und nicht gespeichert. Ändern und
Löschen laufen über die Routen unter `/dokumente/{id}` (`document_pages.py`); ihre Abweisungen
zeigt `documents_page` hier im Reiter.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from moarcoal.defaults import DEFAULT_YEAR
from moarcoal.documents import DocumentKind, IntakeRejected, references_to
from moarcoal.issuer_field import IssuerChoice, resolve_issuer
from moarcoal.previews import preview_kind
from moarcoal.proposals import proposals_of
from moarcoal.storage import Document, Issuer, State, entry_checksum, name_key
from moarcoal.web import document_kinds, render, store_of, user_of, year_of

router = APIRouter(prefix="/belege/dokumente")

WITHOUT_KIND = "none"
"""Filterwert für „Beleg“: Dokumente ohne Dokumentart."""

WITHOUT_ISSUER = "none"
"""Filterwert für „ohne Aussteller“."""

YEAR_NOT_A_NUMBER = "Steuerjahr: ganze Zahl, z. B. 2025"

REFERENCE_LABELS = {
    "Proposal": "Vorschlag",
    "AbortedExtraction": "Abgebrochene Auslesung",
    "Snapshot": "Schnappschuss",
    "ProtocolReading": "Einlesung",
    "WageTaxCertificate": "Einlesung",
}
"""Bezeichnungen für die Einträge, die auf ein Dokument verweisen; sonst gilt der Name im Code."""


class DocumentState(StrEnum):
    """Der abgeleitete Zustand eines Dokuments, in der Reihenfolge des Filters; ohne Art `BELEG`."""

    TO_CONFIRM = "zu bestätigen"
    TO_EXTRACT = "auszulesen"
    DONE = "fertig"
    BELEG = "Beleg"


def document_state(
    state: State, kinds: Mapping[str, DocumentKind], document: Document
) -> DocumentState:
    """„zu bestätigen“ (der neueste Vorschlag hat offene Felder), „auszulesen“ (die Art hat eine
    Auslese-Vorlage, aber es gibt keinen Vorschlag), „fertig“ oder, ohne Art, „Beleg“ (neutral)."""
    if not document.document_kind:
        return DocumentState.BELEG
    proposals = proposals_of(state, document)
    if proposals:
        return DocumentState.TO_CONFIRM if proposals[-1].open_keys else DocumentState.DONE
    kind = kinds.get(document.document_kind)
    if kind is not None and kind.extraction_template:
        return DocumentState.TO_EXTRACT
    return DocumentState.DONE


def filter_documents(
    state: State,
    user: str,
    kinds: Mapping[str, DocumentKind],
    *,
    kind: str = "",
    year: int | None = None,
    issuer: str = "",
    query: str = "",
    status: str = "",
) -> list[Document]:
    """Die Dokumente von `user`, die alle gesetzten Filter erfüllen, nach Pfad sortiert.

    `kind` ist ein Schlüssel oder `WITHOUT_KIND`, `issuer` eine Kennung oder `WITHOUT_ISSUER`,
    `status` ein Zustand aus `document_state`, leer jeweils für alle; `year` trifft Dokumente,
    deren Bezugszeitraum das Jahr berührt; `query` sucht ohne Groß-/Kleinschreibung in Pfad,
    Ablageort, Art und Namen und Aliassen des Ausstellers.
    """
    issuers = {i.address: i for i in state.of_kind(Issuer)}
    needle = name_key(query)
    found: list[Document] = []
    for document in state.of_kind(Document):
        if document.owner != user:
            continue
        if kind and (document.document_kind or WITHOUT_KIND) != kind:
            continue
        if issuer and (document.issuer.id if document.issuer else WITHOUT_ISSUER) != issuer:
            continue
        if year is not None and not document.touches_year(year):
            continue
        if status and document_state(state, kinds, document) != status:
            continue
        owner = issuers.get(document.issuer) if document.issuer else None
        kind_entry = kinds.get(document.document_kind or "")
        texts = [document.site, document.path, kind_entry.title if kind_entry else ""]
        texts += [owner.name, *owner.aliases] if owner else []
        if needle and not any(needle in name_key(text) for text in texts):
            continue
        found.append(document)
    return sorted(found, key=lambda d: (d.path, d.site, d.id))


def document_detail(
    request: Request, document: Document, issuer_text: str = "", year: str = ""
) -> dict[str, Any]:
    """Alles, was `documents/_detail.html` für den Kopf eines Dokuments braucht (Seite
    Reiter Dokumente und Ablage). `issuer_text` und `year` stellen eine
    abgewiesene Eingabe wieder her."""
    state = store_of(request).state()
    kinds = document_kinds(request)
    kind = kinds.get(document.document_kind or "")
    proposals = proposals_of(state, document)
    return {
        "document": document,
        "issuer": state.get(document.issuer) if document.issuer else None,
        "issuer_text": issuer_text,
        "year": year,
        "kinds": list(kinds.values()),
        "references": references_to(state, document),
        "checksum": entry_checksum(document),
        "labels": REFERENCE_LABELS,
        "default_year": DEFAULT_YEAR,
        "kind": kind,
        "template": None if kind is None else kind.extraction_template,
        "proposal": proposals[-1] if proposals else None,
    }


@dataclass(frozen=True)
class DocumentChoice:
    """Aussteller, Art und Jahr aus dem Formular eines Dokuments (Aufnehmen oder Ändern).

    `kind_key` ist leer für „Beleg“ und `None`, wenn das Formular keine Art schickt (gesperrt);
    `year` ist `DEFAULT_YEAR`, wenn die Art keinen Bezugszeitraum hat.
    """

    issuer: IssuerChoice
    kind_key: str | None
    year: int


def read_document_choice(
    state: State, kinds: Mapping[str, DocumentKind], fields: Mapping[str, str]
) -> DocumentChoice | IntakeRejected:
    """Liest Art, Jahr und Aussteller aus den Formularfeldern `kind`, `year` und denen des
    Aussteller-Felds; was sich nicht lesen lässt, weist es ab wie `take_in`."""
    kind_key = fields.get("kind")
    kind = kinds.get(kind_key or "")
    if kind_key and kind is None:
        return IntakeRejected(("Bitte eine Dokumentart wählen.",))
    year = DEFAULT_YEAR
    if kind is not None and kind.has_period:
        given = year_of(fields.get("year", ""))
        if given is None:
            return IntakeRejected((YEAR_NOT_A_NUMBER,))
        year = given
    issuer = resolve_issuer(state, fields)
    if isinstance(issuer, str):
        return IntakeRejected((issuer,))
    return DocumentChoice(issuer, kind_key, year)


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    art: str = "",
    jahr: str = "",
    aussteller: str = "",
    zustand: str = "",
    dokument: str = "",
) -> HTMLResponse:
    filters = {"q": q, "art": art, "jahr": jahr, "aussteller": aussteller, "zustand": zustand}
    return documents_page(request, filters=filters, selected=dokument)


def documents_page(
    request: Request,
    status_code: int = 200,
    *,
    filters: dict[str, str] | None = None,
    selected: str = "",
    notice: str = "",
    existing: Document | None = None,
    issuer_text: str = "",
    year: str = "",
) -> HTMLResponse:
    """Der Reiter Dokumente mit dem Dokument `selected` (Kennung) rechts. `notice` ist eine
    Abweisung (mit `existing`, dem vorhandenen Dokument bei „Existiert bereits“); `issuer_text`
    und `year` stellen die abgewiesene Eingabe wieder her."""
    filters = filters or dict.fromkeys(("q", "art", "jahr", "aussteller", "zustand"), "")
    store = store_of(request)
    state = store.state()
    kinds = document_kinds(request)
    documents = filter_documents(
        state,
        user_of(request),
        kinds,
        kind=filters["art"],
        year=year_of(filters["jahr"]),
        issuer=filters["aussteller"],
        query=filters["q"],
        status=filters["zustand"],
    )
    chosen = next((d for d in documents if d.id == selected), None)
    issuers = {i.id: i for i in state.of_kind(Issuer)}
    return render(
        request,
        "documents/list.html",
        status_code,
        documents=documents,
        states={d.id: document_state(state, kinds, d) for d in documents},
        document_states=[s for s in DocumentState if s is not DocumentState.BELEG],
        selected=chosen,
        detail=document_detail(request, chosen, issuer_text, year) if chosen else None,
        issuer_names={i.id: i.name for i in issuers.values()},
        issuer_list=sorted(issuers.values(), key=lambda i: name_key(i.name)),
        kind_titles={k.key: k.title for k in kinds.values()},
        filters=filters,
        base=urlencode({k: v for k, v in filters.items() if v}),
        preview_kind=chosen and preview_kind(chosen.path),
        preview_url=chosen and f"/dokumente/{chosen.id}/datei",
        without_kind=WITHOUT_KIND,
        without_issuer=WITHOUT_ISSUER,
        notice=notice,
        existing=existing,
    )
