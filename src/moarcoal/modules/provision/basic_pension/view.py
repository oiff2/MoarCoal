"""Die Anbieterbescheinigungen Basisrente eines Jahrs für die Seite Vorsorge: eingelesene
Bescheinigung, ihr Dokument und die Verträge, denen sie über die Vertragsnummer zugeordnet ist.
Rein: Stand rein, Zeilen raus."""

from collections.abc import Sequence
from dataclasses import dataclass

from moarcoal.modules.provision.basic_pension.entries import BasicPensionCertificate
from moarcoal.modules.provision.basic_pension.reading import BASIC_PENSION_CERTIFICATE
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, Document, number_key


@dataclass(frozen=True)
class PensionRow:
    """Eine Bescheinigung des Jahrs mit ihrem Dokument und den Verträgen des Nutzers mit
    derselben Vertragsnummer (leer: „ohne Vertrag“)."""

    certificate: BasicPensionCertificate
    document: Document
    agreements: tuple[Agreement, ...]


def pension_rows(
    state: ModuleState, year: int, agreements: Sequence[Agreement]
) -> list[PensionRow]:
    """Die eingelesenen Bescheinigungen von `year`, nach Pfad des Dokuments sortiert; `agreements`
    sind die Verträge des Nutzers. Eine Bescheinigung gehört zu den Verträgen mit gleicher
    Vertragsnummer (Groß-/Kleinschreibung und Leerraum egal); ein Vertrag ohne Nummer gehört zu
    keiner."""
    documents = {d.address: d for d in state.documents(BASIC_PENSION_CERTIFICATE.key)}
    rows: list[PensionRow] = []
    for certificate in state.all(BasicPensionCertificate):
        document = documents.get(certificate.document)
        if certificate.year != year or document is None:
            continue
        wanted = number_key(certificate.contract_number)
        matching = tuple(a for a in agreements if wanted and number_key(a.number) == wanted)
        rows.append(PensionRow(certificate, document, matching))
    return sorted(rows, key=lambda r: r.document.path)
