"""Vertrag aus einer eingelesenen Bescheinigung anlegen: der Vertrag (Vertragspartner = Aussteller
des Dokuments, bei der Basisrente mit der Vertragsnummer der Bescheinigung) und seine Steuerliche
Bedeutung in einem Vorgang. Rein: Stand rein, Änderungen raus; geschrieben wird über
`Store.apply` (Anbindung in `pages.py`)."""

from dataclasses import dataclass

from moarcoal.agreements import agreement_changes
from moarcoal.issuer_field import IssuerChoice
from moarcoal.modules.provision.basic_pension.entries import BasicPensionCertificate
from moarcoal.modules.provision.basic_pension.reading import BASIC_PENSION_CERTIFICATE
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.health_certificate.entries import HealthContributionCertificate
from moarcoal.modules.provision.health_certificate.reading import HEALTH_CONTRIBUTION_CERTIFICATE
from moarcoal.modules.provision.meaning import meaning_changes
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, Change, Document, Put


@dataclass(frozen=True)
class CertificateOrigin:
    """Woraus ein Vertrag entstünde: die Bedeutung, die die Bescheinigung verlangt, ihr
    Dokument und die Vertragsnummer (nur bei der Basisrente, sonst leer)."""

    meaning: TaxMeaning
    document: Document
    number: str


def origin_of(state: ModuleState, certificate_id: str) -> CertificateOrigin | None:
    """Die Bescheinigung des Nutzers (Beitragsbescheinigung oder Anbieterbescheinigung Basisrente)
    mit dieser Kennung, `None` wenn es sie nicht gibt oder ihr Dokument fehlt."""
    for health in state.all(HealthContributionCertificate):
        if health.id == certificate_id:
            documents = {d.address: d for d in state.documents(HEALTH_CONTRIBUTION_CERTIFICATE.key)}
            document = documents.get(health.document)
            if document is None:
                return None
            return CertificateOrigin(TaxMeaning.PRIVATE_HEALTH_CARE, document, "")
    for pension in state.all(BasicPensionCertificate):
        if pension.id == certificate_id:
            documents = {d.address: d for d in state.documents(BASIC_PENSION_CERTIFICATE.key)}
            document = documents.get(pension.document)
            if document is None:
                return None
            return CertificateOrigin(TaxMeaning.BASIC_PENSION, document, pension.contract_number)
    return None


def agreement_from_certificate_changes(
    state: ModuleState, origin: CertificateOrigin, entry_id: str
) -> list[Change]:
    """Die Änderungen, die den Vertrag und seine Steuerliche Bedeutung anlegen: Vertragspartner
    ist der Aussteller des Dokuments, die Bezeichnung die Bedeutung, die Art „Versicherung“.
    Wirft `AgreementInvalid`, wenn das Dokument keinen Aussteller hat."""
    fields = {
        "name": origin.meaning.label,
        "number": origin.number,
        "category": "Versicherung",
    }
    changes = agreement_changes(state.user, entry_id, IssuerChoice(origin.document.issuer), fields)
    agreement = next(
        c.entry for c in changes if isinstance(c, Put) and isinstance(c.entry, Agreement)
    )
    return [*changes, *meaning_changes(state, agreement, origin.meaning, "")]
