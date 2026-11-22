"""Seiten der Kirchensteuerzahlungen: erfassen, ändern, löschen auf der Seite der Anlage SA.

Das Formular steht aufklappend unter den Feldern der Anlage SA (`tax_year/_kirchensteuer.html`);
jede Antwort, auch eine Abweisung, zeigt diese Seite. Geschrieben wird nur über `apply`, die Regeln
prüft der Schreibweg (`check_payment`).
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR, year_of
from moarcoal.modules.tax_year.church_tax import MAX_CENTS, ChurchTaxPayment
from moarcoal.modules.tax_year.church_tax_view import Fields, PaymentForm, prefill_from, sent_form
from moarcoal.modules.tax_year.entries import MODULE_KEY, TEXT_MAX
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Applied,
    Change,
    Delete,
    EntryAddress,
    Put,
    new_id,
)
from moarcoal.values.model import format_eur, parse_cents
from moarcoal.web.helpers import (
    entry_of,
    form_fields,
    module_state,
    rejection_reasons,
    store_of,
    user_of,
    validated,
)

DIRECTIONS = {"paid": "gezahlt", "refunded": "erstattet"}
SA_SLUG = "sa"

HINTS = {
    "date": f"Datum: gültiges Datum im Jahr {MIN_YEAR} bis {MAX_YEAR}",
    "amount_cents": f"Betrag: größer als 0 und höchstens {format_eur(MAX_CENTS)}, mit höchstens "
    "zwei Nachkommastellen, z. B. 1.234,50",
    "benefit_type": f"Art der Leistung: angeben, höchstens {TEXT_MAX} Zeichen",
    "document": "Dokument: aus der Liste wählen",
}


def build_payment(
    fields: Fields, owner: str, entry_id: str
) -> tuple[ChurchTaxPayment | None, list[str]]:
    """Formular -> Kirchensteuerzahlung; sonst die Hinweise je Feld."""
    direction = fields.get("direction", "")
    if direction not in DIRECTIONS:
        return None, ["Gezahlt oder erstattet: eines wählen"]
    document = fields.get("document", "").strip()
    try:
        address = EntryAddress(kind="Document", id=document) if document else None
    except ValueError:
        return None, [HINTS["document"]]
    return validated(
        ChurchTaxPayment,
        {
            "id": entry_id,
            "owner": owner,
            "date": fields.get("date", ""),
            "amount_cents": parse_cents(fields.get("amount", "")),
            "refunded": direction == "refunded",
            "benefit_type": fields.get("kind", "").strip(),
            "document": address,
        },
        HINTS,
    )


type RenderSa = Callable[[Request, int, int, PaymentForm | None], HTMLResponse]
"""Die Seite der Anlage SA im Jahr, mit Status und dem abgeschickten Formular; `None`-Jahr gibt es
nicht, die Anbindung wählt das Jahr der Seite."""


def add_routes(router: APIRouter, render_sa: RenderSa) -> None:
    """Hängt die Routen der Kirchensteuerzahlungen an das Steuerjahr."""

    def own_state(request: Request) -> ModuleState:
        return module_state(request, MODULE_KEY)

    def page_year(fields: Fields, fallback: int | None = None) -> int:
        """Das Jahr der Seite, von der das Formular kam; sonst `fallback`, sonst das Jahr des
        Datums, sonst das Vorgabejahr."""
        return (
            year_of(fields.get("page_year", ""), in_range=True)
            or fallback
            or year_of(fields.get("date", "")[:4], in_range=True)
            or DEFAULT_YEAR
        )

    def write(
        request: Request, change: Change, entry_id: str, fields: Fields, year: int
    ) -> Response:
        result = store_of(request).apply([change])
        if not isinstance(result, Applied):
            sent = sent_form(entry_id, fields, rejection_reasons(result))
            return render_sa(request, year, 409, sent)
        return RedirectResponse(f"/steuerjahr/anlage-{SA_SLUG}/{year}", status_code=303)

    @router.get("/kirchensteuer/{entry_id}")
    def open_payment(request: Request, entry_id: str) -> Response:
        """Die Adresse einer Zahlung: die Seite der Anlage SA im Jahr der Zahlung, sie offen."""
        entry = entry_of(own_state(request), ChurchTaxPayment, entry_id)
        return RedirectResponse(
            f"/steuerjahr/anlage-{SA_SLUG}/{entry.year}?eintrag={entry.id}", status_code=303
        )

    @router.post("/kirchensteuer")
    def create(request: Request, fields: Annotated[Fields, Depends(form_fields)]) -> Response:
        year = page_year(fields)
        entry, errors = build_payment(fields, user_of(request), new_id())
        if entry is None:
            return render_sa(request, year, 422, sent_form("", fields, errors))
        return write(request, Put(entry), "", fields, year)

    @router.post("/kirchensteuer/{entry_id}")
    def update(
        request: Request, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
    ) -> Response:
        current = entry_of(own_state(request), ChurchTaxPayment, entry_id)
        year = page_year(fields, current.year)
        entry, errors = build_payment(fields, user_of(request), entry_id)
        if entry is None:
            return render_sa(request, year, 422, sent_form(entry_id, fields, errors))
        change = Put(entry, expected=fields.get("checksum", ""))
        return write(request, change, entry_id, fields, year)

    @router.post("/kirchensteuer/{entry_id}/loeschen")
    def delete(
        request: Request, entry_id: str, fields: Annotated[Fields, Depends(form_fields)]
    ) -> Response:
        current = entry_of(own_state(request), ChurchTaxPayment, entry_id)
        year = page_year(fields, current.year)
        change = Delete(current.address, expected=fields.get("checksum", ""))
        return write(request, change, entry_id, prefill_from(current) | fields, year)
