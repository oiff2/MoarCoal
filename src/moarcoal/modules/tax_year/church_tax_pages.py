"""Seiten der Kirchensteuerzahlungen: erfassen, ändern, löschen auf der Seite der Anlage SA.

Das Formular steht aufklappend unter den Feldern der Anlage SA (`tax_year/_kirchensteuer.html`);
jede Antwort, auch eine Abweisung, zeigt diese Seite. Geschrieben wird nur über `apply`, die Regeln
prüft der Schreibweg (`check_payment`).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR, year_of
from moarcoal.modules.tax_year.church_tax import MAX_CENTS, ChurchTaxPayment, payments_in_year
from moarcoal.modules.tax_year.entries import MODULE_KEY, TEXT_MAX
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Applied,
    Change,
    Delete,
    EntryAddress,
    Put,
    entry_checksum,
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
from moarcoal.web.links import document_url

type Fields = dict[str, str]

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


def prefill_from(entry: ChurchTaxPayment) -> Fields:
    euros, cents = divmod(entry.amount_cents, 100)
    return {
        "date": entry.date.isoformat(),
        "amount": f"{euros},{cents:02d}",
        "kind": entry.benefit_type,
        "direction": "refunded" if entry.refunded else "paid",
        "document": "" if entry.document is None else entry.document.id,
    }


@dataclass(frozen=True)
class PaymentForm:
    """Ein Formular der Seite: zu einer Zahlung (`entry_id`) oder neu (leer); `open` = offen."""

    entry_id: str
    checksum: str
    values: Fields
    errors: tuple[str, ...] = ()
    open: bool = False

    @property
    def action(self) -> str:
        base = "/steuerjahr/kirchensteuer"
        return f"{base}/{self.entry_id}" if self.entry_id else base


@dataclass(frozen=True)
class DocumentChoice:
    id: str
    label: str


@dataclass(frozen=True)
class ChurchView:
    """Was die Seite der Anlage SA für die Kirchensteuerzahlungen braucht."""

    year: int
    payments: tuple[tuple[ChurchTaxPayment, PaymentForm, str | None], ...]  # mit Link zum Beleg
    new: PaymentForm
    documents: tuple[DocumentChoice, ...]


def sent_form(entry_id: str, fields: Fields, errors: list[str]) -> PaymentForm:
    """Ein abgewiesenes Formular: Eingabe und Gründe bleiben stehen, es ist offen."""
    return PaymentForm(entry_id, fields.get("checksum", ""), fields, tuple(errors), True)


def church_view(
    state: ModuleState, year: int, open_entry: str, sent: PaymentForm | None
) -> ChurchView:
    """Die Zahlungen des Jahrs je mit ihrem Formular; das abgeschickte ersetzt seines."""
    forms: list[tuple[ChurchTaxPayment, PaymentForm, str | None]] = []
    for entry in payments_in_year(state, year):
        form = PaymentForm(
            entry.id, entry_checksum(entry), prefill_from(entry), open=entry.id == open_entry
        )
        if sent is not None and sent.entry_id == entry.id:
            form = replace(sent, checksum=sent.checksum or form.checksum)
        link = None if entry.document is None else document_url(entry.document.id)
        forms.append((entry, form, link))
    new = sent if sent is not None and not sent.entry_id else PaymentForm("", "", {})
    documents = tuple(
        DocumentChoice(d.id, d.label or PurePath(d.path).name) for d in state.documents()
    )
    return ChurchView(year, tuple(forms), new, documents)


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
