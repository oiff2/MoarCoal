"""Die Jahresbeiträge eines Jahrs für die Seite Vorsorge: je Vertrag mit Steuerlicher Bedeutung
sein Jahresbeitrag und das Formular dazu. Rein: Stand rein, Zeilen raus."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath

from moarcoal.modules.provision.annual_contribution.changes import Fields, contribution_of
from moarcoal.modules.provision.annual_contribution.entries import AnnualContribution
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.meaning import meaning_of, runs_in
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, entry_checksum


@dataclass(frozen=True)
class DocumentChoice:
    id: str
    label: str


@dataclass(frozen=True)
class ContributionRow:
    """Ein Vertrag mit Bedeutung: sein Jahresbeitrag (`None`: noch keiner), dessen Prüfsumme
    (leer: keiner) und die Eingabe des Formulars (Vorbelegung oder abgewiesene Eingabe)."""

    agreement: Agreement
    meaning: TaxMeaning
    contribution: AnnualContribution | None
    checksum: str
    values: Fields
    errors: tuple[str, ...] = field(default=())
    open: bool = False


def prefill(contribution: AnnualContribution | None) -> Fields:
    """Die Vorbelegung des Formulars aus dem Jahresbeitrag; ohne ihn leer."""
    if contribution is None:
        return {}

    def euros(cents: int) -> str:
        whole, rest = divmod(cents, 100)
        return f"{whole},{rest:02d}"

    return {
        "amount": euros(contribution.amount_cents),
        "refund": "" if contribution.refund_cents is None else euros(contribution.refund_cents),
        "document": "" if contribution.document is None else contribution.document.id,
    }


def contribution_rows(
    state: ModuleState,
    year: int,
    agreements: Sequence[Agreement],
    sent: tuple[str, Fields, tuple[str, ...]] | None = None,
) -> list[ContributionRow]:
    """Die Verträge mit Bedeutung, die im Jahr laufen oder einen Jahresbeitrag dafür haben, je mit
    ihrem Jahresbeitrag. `sent` ist die abgewiesene Eingabe (Vertrag, Formular, Gründe): die Zeile
    zeigt sie offen mit den Gründen."""
    rows: list[ContributionRow] = []
    for agreement in agreements:
        meaning = meaning_of(state, agreement)
        contribution = contribution_of(state, agreement, year)
        if meaning is None or (contribution is None and not runs_in(agreement, year)):
            continue
        values, errors, is_open = prefill(contribution), (), False
        if sent is not None and sent[0] == agreement.id:
            values, errors, is_open = sent[1], sent[2], True
        checksum = "" if contribution is None else entry_checksum(contribution)
        rows.append(
            ContributionRow(
                agreement, meaning.meaning, contribution, checksum, values, errors, is_open
            )
        )
    return rows


def document_choices(state: ModuleState) -> tuple[DocumentChoice, ...]:
    """Die Dokumente des Nutzers, aus denen man einen Beleg wählt."""
    return tuple(DocumentChoice(d.id, d.label or PurePath(d.path).name) for d in state.documents())
