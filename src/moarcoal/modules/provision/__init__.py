"""Modul Vorsorge: Beiträge zu Versicherungen und Altersvorsorge (Anlage Vorsorgeaufwand). Die
Teile: die Seite je Steuerjahr mit den Verträgen und ihrer Steuerlichen Bedeutung, dazu die
eingelesene Beitragsbescheinigung Kranken-/Pflegeversicherung."""

from moarcoal.modules.provision.common import MODULE_KEY
from moarcoal.modules.provision.entries import KINDS, AgreementMeaning, TaxMeaning
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
    kinds=KINDS + certificate_entries.KINDS,
    values=certificate_values.VALUES,
    document_kinds=(HEALTH_CONTRIBUTION_CERTIFICATE,),
)

__all__ = [
    "HEALTH_CONTRIBUTION_CERTIFICATE",
    "REGISTRATION",
    "AgreementMeaning",
    "HealthContributionCertificate",
    "TaxMeaning",
]
