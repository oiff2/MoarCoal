"""Seite „Aussteller“: Katalog mit Suche, Detail mit Ändern, Zusammenführen, Löschen (Spec 3.2).

Gelöscht wird nur ohne Verweise; sonst zeigt die Seite die Verweise des Nutzers. Zusammenführen
läuft über eine Folgenseite und eine ausdrückliche Bestätigung; die App schlägt es nie vor.
"""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.expected_documents import expected_name
from moarcoal.issuer_years import (
    IssuerFilter,
    Mark,
    issuer_detail,
    issuer_rows,
    listed,
    years_shown,
)
from moarcoal.personal_details import details_for_issuer, details_of, own_issuer
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    Merge,
    Put,
    State,
    entry_checksum,
    name_key,
)
from moarcoal.storage.entries import referenced_addresses
from moarcoal.storage.issuers import issuer_with_name
from moarcoal.web.helpers import (
    document_kinds,
    entry_of,
    form_fields,
    rejection_reasons,
    render,
    store_of,
    user_of,
    validated,
)
from moarcoal.web.links import (
    issuer_delete_url,
    issuer_merge_url,
    issuer_url,
    issuers_url,
    portal_link,
)

router = APIRouter(prefix="/aussteller")

type Fields = dict[str, str]

FROM_DETAILS = "Der Aussteller kommt aus den Angaben zur Person."

HINTS = {
    "name": "Name: darf nicht leer sein",
    "aliases": "Weitere Namen: einer pro Absatz, keiner leer",
    "portal": "Portal: eine Adresse mit http oder https",
}


def _references(
    state: State, issuer: Issuer, user: str
) -> tuple[list[Document], list[ExpectedDocument]]:
    """Dokumente und Erwartete Belege des Nutzers, die auf den Aussteller verweisen."""
    found = [
        e
        for e in state.entries.values()
        if e.owner == user and issuer.address in referenced_addresses(e)
    ]
    documents = sorted((e for e in found if isinstance(e, Document)), key=lambda d: d.path)
    expected = sorted(
        (e for e in found if isinstance(e, ExpectedDocument)), key=lambda e: (e.start_year, e.id)
    )
    return documents, expected


def _build(fields: Fields, issuer: Issuer, locked: bool = False) -> tuple[Issuer | None, list[str]]:
    """Der geänderte Aussteller; Name und Privatperson bleiben, wenn er aus den Angaben zur
    Person kommt (`locked`)."""
    aliases = tuple(line.strip() for line in fields.get("aliases", "").splitlines() if line.strip())
    return validated(
        Issuer,
        {
            **issuer.model_dump(),
            "name": issuer.name if locked else fields.get("name", "").strip(),
            "aliases": aliases,
            "private_person": issuer.private_person
            if locked
            else fields.get("private_person") == "on",
            "portal": fields.get("portal", "").strip() or None,
            "note": fields.get("note", "").strip() or None,
        },
        HINTS,
        unknown="",
    )


@dataclass(frozen=True)
class _ListState:
    """Suche und Filter der Liste: sie stehen in der Adresse und reisen in jedem Formular der Seite
    mit (versteckte Felder `q` und `filter`)."""

    query: str = ""
    chosen: IssuerFilter = IssuerFilter.ALL

    @classmethod
    def of(cls, query: str, filter_text: str) -> "_ListState":
        return cls(query.strip(), IssuerFilter.parse(filter_text))

    @classmethod
    def kept(cls, fields: Fields) -> "_ListState":
        """Suche und Filter, die ein Formular der Seite mitschickt."""
        return cls.of(fields.get("q", ""), fields.get("filter", ""))

    @property
    def filter_value(self) -> str:
        """Der Filter für die Adresse; „alle“ steht nicht darin."""
        return "" if self.chosen is IssuerFilter.ALL else self.chosen.value

    def issuer_url(self, issuer_id: str) -> str:
        return issuer_url(issuer_id, self.query, self.filter_value)

    def issuers_url(self) -> str:
        return issuers_url(self.query, self.filter_value)

    def with_filter(self, chosen: IssuerFilter) -> "_ListState":
        return _ListState(self.query, chosen)

    def without_query(self) -> "_ListState":
        return _ListState("", self.chosen)


_NOTHING_KEPT = _ListState()


def _issuer(request: Request, issuer_id: str) -> Issuer:
    return entry_of(store_of(request).state(), Issuer, issuer_id)


def _page(
    request: Request,
    selected: Issuer | None = None,
    fields: Fields | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
    holder: Issuer | None = None,
    kept: _ListState = _NOTHING_KEPT,
) -> HTMLResponse:
    """Die eine Seite: links die Liste (Suche und Filter aus der Adresse), rechts das Detail des
    gewählten Ausstellers; ohne Auswahl zeigt die rechte Seite nur einen Hinweis."""
    state = store_of(request).state()
    user = user_of(request)
    details = details_of(state, user)
    own = None if details is None else own_issuer(state, details)
    this_year = datetime.date.today().year
    sites = store_of(request).sites
    rows, found = listed(issuer_rows(state, user, sites, this_year), kept.query, kept.chosen, own)
    kinds = document_kinds(request)

    def expected_label(expected: ExpectedDocument) -> str:
        return expected_name(expected, kinds)

    context: dict[str, object] = {
        "expected_label": expected_label,
        "rows": rows,
        "years": years_shown(this_year),
        "chips": [
            (label, n, kept.with_filter(f).issuers_url(), f is kept.chosen)
            for label, n, f in (
                ("alle", found.all, IssuerFilter.ALL),
                (
                    f"ohne Belege seit {this_year - 1}",
                    found.no_documents,
                    IssuerFilter.NO_DOCUMENTS,
                ),
                ("mit Portal", found.portal, IssuerFilter.PORTAL),
            )
        ],
        "chosen": kept.chosen.value,
        "reset_href": kept.without_query().issuers_url(),
        "marks": list(Mark),
        "query": kept.query,
        "own": own,
        "filter_value": kept.filter_value,
        "row_url": kept.issuer_url,
        "selected": selected,
        "search_action": issuers_url() if selected is None else issuer_url(selected.id),
    }
    if selected is not None:
        documents, expected = _references(state, selected, user)
        context |= {
            "issuer": selected,
            "belege": issuer_detail(state, user, sites, selected, this_year),
            "others": sorted(
                (i for i in state.of_kind(Issuer) if i.id != selected.id),
                key=lambda i: (name_key(i.name), i.id),
            ),
            "checksum": entry_checksum(selected),
            "delete_href": issuer_delete_url(selected.id),
            "merge_href": issuer_merge_url(selected.id),
            "values": fields
            or {
                "name": selected.name,
                "aliases": "\n".join(selected.aliases),
                "private_person": "on" if selected.private_person else "",
                "portal": selected.portal or "",
                "note": selected.note or "",
            },
            "portal_href": portal_link(selected.portal),
            "documents": documents,
            "expected": expected,
            "errors": errors or [],
            "holder": holder,
            "from_details": details_for_issuer(state, selected) is not None,
        }
    return render(request, "issuers/index.html", status_code, **context)


FilterParam = Annotated[
    str, Query(alias="filter")
]  # „filter“ in der Adresse, ohne das Builtin zu überdecken


@router.get("", response_class=HTMLResponse)
def index(request: Request, q: str = "", filter_text: FilterParam = "") -> HTMLResponse:
    return _page(request, kept=_ListState.of(q, filter_text))


@router.get("/{issuer_id}", response_class=Response)
def show(request: Request, issuer_id: str, q: str = "", filter_text: FilterParam = "") -> Response:
    try:
        address = EntryAddress(kind=Issuer.__name__, id=issuer_id)
    except ValueError as error:
        raise HTTPException(404) from error
    found = store_of(request).state().resolve(address)
    kept = _ListState.of(q, filter_text)
    if isinstance(found, Issuer) and found.id != issuer_id:  # zusammengeführt: alte Adresse
        return RedirectResponse(kept.issuer_url(found.id), status_code=308)
    return _page(request, _issuer(request, issuer_id), kept=kept)


def _merge_page(
    request: Request,
    source: Issuer,
    target: Issuer | None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = store_of(request).state()
    user = user_of(request)
    documents, expected = _references(state, source, user)
    return render(
        request,
        "issuers/merge.html",
        status_code,
        source=source,
        target=target,
        checksum=entry_checksum(source),
        merge_href=issuer_merge_url(source.id),
        target_checksum=entry_checksum(target) if target else "",
        documents=documents,
        expected=expected,
        errors=errors or [],
    )


def _target(request: Request, source: Issuer, issuer_id: str) -> Issuer | None:
    try:
        address = EntryAddress(kind=Issuer.__name__, id=issuer_id)
    except ValueError:
        return None
    target = store_of(request).state().get(address)
    return target if isinstance(target, Issuer) and target.id != source.id else None


@router.get("/{issuer_id}/zusammenfuehren", response_class=HTMLResponse)
def merge_preview(request: Request, issuer_id: str, into: str = "") -> HTMLResponse:
    """Folgenseite: ändert nichts, zeigt nur, was das Zusammenführen bewirkt."""
    source = _issuer(request, issuer_id)
    target = _target(request, source, into)
    if target is None:
        raise HTTPException(404)
    return _merge_page(request, source, target)


@router.post("/{issuer_id}/zusammenfuehren")
def merge(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    source = _issuer(request, issuer_id)
    target = _target(request, source, fields.get("into", ""))
    if target is None:
        raise HTTPException(404)
    if fields.get("confirm") != "on":
        return _merge_page(request, source, target, ["Bitte das Zusammenführen bestätigen."], 422)
    result = store_of(request).apply(
        [
            Merge(
                source.address,
                target.address,
                expected=fields.get("checksum", ""),
                expected_into=fields.get("target_checksum", ""),
            )
        ]
    )
    if not isinstance(result, Applied):
        return _merge_page(request, source, target, rejection_reasons(result), 409)
    return RedirectResponse(issuer_url(target.id), status_code=303)


@router.post("/{issuer_id}")
def update(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    locked = details_for_issuer(store_of(request).state(), issuer) is not None
    changed, errors = _build(fields, issuer, locked)
    kept = _ListState.kept(fields)
    if changed is None:
        return _page(request, issuer, fields, errors, 422, kept=kept)
    result = store_of(request).apply([Put(changed, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        others = [i for i in store_of(request).state().of_kind(Issuer) if i.id != issuer.id]
        holder = next(
            (h for n in (changed.name, *changed.aliases) if (h := issuer_with_name(others, n))),
            None,
        )
        reasons = [] if holder else rejection_reasons(result)
        return _page(request, issuer, fields, reasons, 409, holder, kept)
    return RedirectResponse(kept.issuer_url(issuer.id), status_code=303)


@router.post("/{issuer_id}/loeschen")
def delete(
    request: Request, issuer_id: str, fields: Annotated[Fields, Depends(form_fields)]
) -> Response:
    issuer = _issuer(request, issuer_id)
    kept = _ListState.kept(fields)
    if details_for_issuer(store_of(request).state(), issuer) is not None:
        return _page(request, issuer, errors=[FROM_DETAILS], status_code=409, kept=kept)
    result = store_of(request).apply([Delete(issuer.address, expected=fields.get("checksum", ""))])
    if not isinstance(result, Applied):
        return _page(request, issuer, errors=rejection_reasons(result), status_code=409, kept=kept)
    return RedirectResponse(kept.issuers_url(), status_code=303)
