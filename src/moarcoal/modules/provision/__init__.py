"""Modul Vorsorge: Beiträge zu Versicherungen und Altersvorsorge (Anlage Vorsorgeaufwand). Die
Teile: die Seite je Steuerjahr mit den Verträgen und ihrer Steuerlichen Bedeutung, der Jahresbeitrag
je Vertrag, dazu die eingelesene Beitragsbescheinigung Kranken-/Pflegeversicherung und die
Anbieterbescheinigung Basisrente, dazu die Befunde zu Bescheinigung und Vertrag."""

from moarcoal.modules.provision.annual_contribution import entries as contribution_entries
from moarcoal.modules.provision.annual_contribution import values as contribution_values
from moarcoal.modules.provision.annual_contribution.entries import AnnualContribution
from moarcoal.modules.provision.basic_pension import entries as pension_entries
from moarcoal.modules.provision.basic_pension import values as pension_values
from moarcoal.modules.provision.basic_pension.entries import BasicPensionCertificate
from moarcoal.modules.provision.basic_pension.reading import BASIC_PENSION_CERTIFICATE
from moarcoal.modules.provision.common import MODULE_KEY
from moarcoal.modules.provision.entries import KINDS, AgreementMeaning, TaxMeaning
from moarcoal.modules.provision.findings import FINDING_KINDS, provision_findings
from moarcoal.modules.provision.health_certificate import entries as certificate_entries
from moarcoal.modules.provision.health_certificate import values as certificate_values
from moarcoal.modules.provision.health_certificate.entries import HealthContributionCertificate
from moarcoal.modules.provision.health_certificate.reading import HEALTH_CONTRIBUTION_CERTIFICATE
from moarcoal.modules.provision.pages import router
from moarcoal.registration import ModuleRegistration

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Vorsorge",
    nav_label="Vorsorge",
    nav_url="/vorsorge",
    router=router,
    kinds=KINDS + certificate_entries.KINDS + contribution_entries.KINDS + pension_entries.KINDS,
    values=certificate_values.VALUES + contribution_values.VALUES + pension_values.VALUES,
    capture_url=contribution_values.capture_url,
    document_kinds=(HEALTH_CONTRIBUTION_CERTIFICATE, BASIC_PENSION_CERTIFICATE),
    finding_kinds=FINDING_KINDS,
    findings=provision_findings,
)

__all__ = [
    "BASIC_PENSION_CERTIFICATE",
    "HEALTH_CONTRIBUTION_CERTIFICATE",
    "REGISTRATION",
    "AgreementMeaning",
    "AnnualContribution",
    "BasicPensionCertificate",
    "HealthContributionCertificate",
    "TaxMeaning",
]
