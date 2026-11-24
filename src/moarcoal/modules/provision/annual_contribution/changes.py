"""Fachkern des Jahresbeitrags: den Jahresbeitrag eines Vertrags finden, das Formular zum Eintrag
machen und die Änderungen fürs Erfassen, Ändern und Löschen. Rein: Stand rein, Ergebnis oder
Änderungen raus; geschrieben wird über `Store.apply` (Anbindung in `pages.py`)."""

from collections.abc import Mapping

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.modules.provision.annual_contribution.entries import MAX_CENTS, AnnualContribution
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, Change, Delete, EntryAddress, Put
from moarcoal.values.model import format_eur, parse_cents
from moarcoal.web.helpers import validated

type Fields = Mapping[str, str]

HINTS = {
    "amount_cents": f"Betrag: 0 oder mehr und höchstens {format_eur(MAX_CENTS)}, mit höchstens "
    "zwei Nachkommastellen, z. B. 1.234,50 (0 heißt: ausdrücklich nichts gezahlt)",
    "refund_cents": f"Erstattung: leer oder 0 bis {format_eur(MAX_CENTS)}, mit höchstens zwei "
    "Nachkommastellen, z. B. 120,00",
    "document": "Beleg: aus der Liste wählen",
    "year": f"Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
}


def contribution_of(
    state: ModuleState, agreement: Agreement, year: int
) -> AnnualContribution | None:
    """Der Jahresbeitrag des Vertrags im Jahr, falls es einen gibt."""
    return next(
        (
            c
            for c in state.all(AnnualContribution)
            if c.agreement == agreement.address and c.year == year
        ),
        None,
    )


def net_cents(contribution: AnnualContribution) -> int:
    """Betrag abzüglich Erstattung in Cent, ungerundet; ohne angegebene Erstattung der Betrag."""
    if contribution.refund_cents is None:
        return contribution.amount_cents
    return contribution.amount_cents - contribution.refund_cents


def build_contribution(
    fields: Fields, owner: str, agreement: Agreement, year: int, entry_id: str | None = None
) -> tuple[AnnualContribution | None, list[str]]:
    """Formular -> Jahresbeitrag des Vertrags im Jahr; sonst die Hinweise je Feld. Der Betrag ist
    Pflicht (leer ist keine 0), die Erstattung darf fehlen."""
    refund_text = fields.get("refund", "").strip()
    refund = parse_cents(refund_text) if refund_text else None
    document_text = fields.get("document", "").strip()
    try:
        document = EntryAddress(kind="Document", id=document_text) if document_text else None
    except ValueError:
        return None, [HINTS["document"]]
    data: dict[str, object] = {
        "owner": owner,
        "agreement": agreement.address,
        "year": year,
        "amount_cents": parse_cents(fields.get("amount", "")),
        "refund_cents": refund,
        "document": document,
    }
    if entry_id is not None:
        data["id"] = entry_id
    entry, errors = validated(AnnualContribution, data, HINTS)
    if refund_text and refund is None:  # unlesbar, nicht "keine Erstattung"
        return None, [*errors, HINTS["refund_cents"]]
    return entry, errors


def contribution_changes(
    existing: AnnualContribution | None, entry: AnnualContribution, seen: str
) -> list[Change]:
    """Die Änderung, die `entry` anlegt (`existing` ist `None`) oder den vorhandenen Jahresbeitrag
    ersetzt (`entry` trägt dann dessen Kennung). `seen` ist die Prüfsumme des Eintrags, den der
    Nutzer vor sich hatte (leer, wenn er keinen sah); `apply` weist ab, wenn der Eintrag
    inzwischen anders ist."""
    if existing is None:
        return [Put(entry, expected=seen or None)]
    return [Put(entry, expected=seen)]


def delete_changes(existing: AnnualContribution, seen: str) -> list[Change]:
    return [Delete(existing.address, expected=seen)]
