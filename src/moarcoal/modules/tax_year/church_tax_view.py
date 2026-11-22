"""Was die Seite der Anlage SA für die Kirchensteuerzahlungen zeigt, ohne Web: Formulare zu den
Zahlungen des Jahrs (`church_view`), das abgewiesene Formular, Vorbelegung.

Rein: Stand rein, Ansicht raus. Die Routen (`church_tax_pages.py`) und die Vorlage
(`tax_year/_kirchensteuer.html`) nutzen sie; Anlage SA bindet sie als Sonderteil ein.
"""

from dataclasses import dataclass, replace
from pathlib import PurePath

from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment, payments_in_year
from moarcoal.registration import ModuleState
from moarcoal.storage import entry_checksum
from moarcoal.web.links import document_url

type Fields = dict[str, str]


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
