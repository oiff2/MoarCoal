"""Die Beitragsbescheinigungen eines Jahrs für die Seite Vorsorge: eingelesene Bescheinigung,
ihr Dokument und die Verträge, denen sie über den Aussteller zugeordnet ist. Rein: Stand rein,
Zeilen raus."""

from collections.abc import Sequence
from dataclasses import dataclass

from moarcoal.modules.provision.health_certificate.entries import (
    Characteristic,
    HealthContributionCertificate,
)
from moarcoal.modules.provision.health_certificate.reading import HEALTH_CONTRIBUTION_CERTIFICATE
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, Document


@dataclass(frozen=True)
class CertificateRow:
    """Eine Bescheinigung des Jahrs mit ihrem Dokument und den laufenden Verträgen desselben
    Ausstellers (leer: „ohne Vertrag“)."""

    certificate: HealthContributionCertificate
    document: Document
    agreements: tuple[Agreement, ...]

    @property
    def has_private_block(self) -> bool:
        """Ob mindestens ein Block das Merkmal „privat“ hat; nur dann braucht die Bescheinigung
        einen Vertrag mit der Bedeutung Kranken- und Pflegeversicherung privat."""
        return any(line.characteristic is Characteristic.PRIVATE for line in self.certificate.lines)


def certificate_rows(
    state: ModuleState, year: int, running: Sequence[Agreement]
) -> list[CertificateRow]:
    """Die eingelesenen Bescheinigungen von `year`, nach Dokument sortiert; `running` sind die
    Verträge, die im Jahr laufen. Eine Bescheinigung gehört zu den Verträgen ihres Ausstellers;
    hat das Dokument keinen, gehört sie zu keinem."""
    documents = {d.address: d for d in state.documents(HEALTH_CONTRIBUTION_CERTIFICATE.key)}
    rows: list[CertificateRow] = []
    for certificate in state.all(HealthContributionCertificate):
        document = documents.get(certificate.document)
        if certificate.year != year or document is None:
            continue
        matching = tuple(
            a for a in running if document.issuer is not None and a.issuer == document.issuer
        )
        rows.append(CertificateRow(certificate, document, matching))
    return rows
