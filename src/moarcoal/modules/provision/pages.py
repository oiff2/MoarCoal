"""Die eine Seite des Moduls Vorsorge (`/vorsorge`): die Verträge eines Steuerjahrs mit ihrer
Steuerlichen Bedeutung und die eingelesenen Beitragsbescheinigungen. Geschrieben wird nur über
`apply`; jede Antwort, auch eine Abweisung, zeigt diese Seite."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import year_of
from moarcoal.modules.provision.annual_contribution.changes import (
    Fields,
    build_contribution,
    contribution_changes,
    contribution_of,
    delete_changes,
)
from moarcoal.modules.provision.annual_contribution.view import (
    contribution_rows,
    document_choices,
)
from moarcoal.modules.provision.common import MODULE_KEY
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.health_certificate.view import certificate_rows
from moarcoal.modules.provision.links import (
    contribution_delete_url,
    contribution_url,
    meaning_url,
    provision_url,
)
from moarcoal.modules.provision.meaning import (
    MeaningInvalid,
    meaning_changes,
    meaning_of,
    parse_meaning,
    running_agreements,
)
from moarcoal.storage import Agreement, Applied, Change, Issuer, entry_checksum
from moarcoal.web.helpers import (
    chosen_year,
    entry_of,
    form_fields,
    module_state,
    rejection_reasons,
    render,
    store_of,
    user_of,
)
from moarcoal.web.links import document_url

router = APIRouter(prefix="/vorsorge")


@dataclass(frozen=True)
class AgreementRow:
    """Ein laufender Vertrag der Seite: Vertrag, Vertragspartner, seine Bedeutung (`None`: keine)
    und die Prüfsumme des Eintrags der Bedeutung (leer: es gibt keinen)."""

    agreement: Agreement
    partner: str
    meaning: TaxMeaning | None
    checksum: str


def provision_page(
    request: Request,
    year: int,
    status_code: int = 200,
    *,
    errors: tuple[str, ...] = (),
    failed: tuple[str, str] | None = None,
    sent_contribution: tuple[str, Fields, tuple[str, ...]] | None = None,
) -> HTMLResponse:
    """Die Seite Vorsorge für `year`. `failed` ist der Vertrag (Kennung) und die Wahl einer
    abgewiesenen Eingabe: die Zeile zeigt sie mit den Gründen `errors`. `sent_contribution` ist
    die abgewiesene Eingabe eines Jahresbeitrags (Vertrag, Formular, Gründe)."""
    state = module_state(request, MODULE_KEY)
    everything = store_of(request).state()
    rows: list[AgreementRow] = []
    running = running_agreements(state.agreements(), year)
    for agreement in running:
        found = meaning_of(state, agreement)
        issuer = everything.get(agreement.issuer)
        rows.append(
            AgreementRow(
                agreement,
                issuer.name if isinstance(issuer, Issuer) else "",
                None if found is None else found.meaning,
                "" if found is None else entry_checksum(found),
            )
        )
    return render(
        request,
        "provision/index.html",
        status_code,
        year=year,
        rows=rows,
        certificates=certificate_rows(state, year, running),
        contributions=contribution_rows(state, year, state.agreements(), sent_contribution),
        documents=document_choices(state),
        contribution_url=contribution_url,
        contribution_delete_url=contribution_delete_url,
        document_url=document_url,
        meanings=list(TaxMeaning),
        meaning_url=meaning_url,
        errors=errors,
        failed=failed,
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return provision_page(request, chosen_year(request))


@router.post("/bedeutung/{agreement_id}")
def set_meaning(
    request: Request, agreement_id: str, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    """Die Steuerliche Bedeutung eines Vertrags setzen, ändern oder (leere Wahl) entfernen."""
    year = year_of(fields.get("year", ""), in_range=True) or chosen_year(request)
    state = module_state(request, MODULE_KEY)
    agreement = entry_of(store_of(request).state(), Agreement, agreement_id, user_of(request))
    choice = fields.get("meaning", "")
    try:
        changes = meaning_changes(
            state, agreement, parse_meaning(choice), fields.get("checksum", "")
        )
    except MeaningInvalid as error:
        return provision_page(
            request, year, 422, errors=(str(error),), failed=(agreement_id, choice)
        )
    result = store_of(request).apply(changes)
    if not isinstance(result, Applied):
        reasons = tuple(rejection_reasons(result))
        return provision_page(request, year, 409, errors=reasons, failed=(agreement_id, choice))
    return RedirectResponse(provision_url(year), status_code=303)


def _contribution_year(request: Request, fields: Fields) -> int:
    return year_of(fields.get("year", ""), in_range=True) or chosen_year(request)


def _write_contribution(
    request: Request, changes: list[Change], year: int, agreement_id: str, fields: Fields
) -> Response:
    """Über `apply` schreiben; eine Abweisung zeigt die Seite mit der Eingabe und den Gründen."""
    result = store_of(request).apply(changes)
    if not isinstance(result, Applied):
        sent = (agreement_id, fields, tuple(rejection_reasons(result)))
        return provision_page(request, year, 409, sent_contribution=sent)
    return RedirectResponse(provision_url(year), status_code=303)


@router.post("/jahresbeitrag/{agreement_id}")
def save_contribution(
    request: Request, agreement_id: str, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    """Den Jahresbeitrag eines Vertrags erfassen oder (mit seiner Prüfsumme) ändern."""
    year = _contribution_year(request, fields)
    state = module_state(request, MODULE_KEY)
    agreement = entry_of(store_of(request).state(), Agreement, agreement_id, user_of(request))
    existing = contribution_of(state, agreement, year)
    entry, errors = build_contribution(
        fields, user_of(request), agreement, year, None if existing is None else existing.id
    )
    if entry is None:
        sent = (agreement_id, fields, tuple(errors))
        return provision_page(request, year, 422, sent_contribution=sent)
    changes = contribution_changes(existing, entry, fields.get("checksum", ""))
    return _write_contribution(request, changes, year, agreement_id, fields)


@router.post("/jahresbeitrag/{agreement_id}/loeschen")
def delete_contribution(
    request: Request, agreement_id: str, fields: Annotated[dict[str, str], Depends(form_fields)]
) -> Response:
    """Den Jahresbeitrag eines Vertrags löschen."""
    year = _contribution_year(request, fields)
    state = module_state(request, MODULE_KEY)
    agreement = entry_of(store_of(request).state(), Agreement, agreement_id, user_of(request))
    existing = contribution_of(state, agreement, year)
    if existing is None:
        raise HTTPException(status_code=404)
    changes = delete_changes(existing, fields.get("checksum", ""))
    return _write_contribution(request, changes, year, agreement_id, fields)
