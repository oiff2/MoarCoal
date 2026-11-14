"""Modul Arbeit: Angaben zur Anlage N von Hand erfassen (Durchstich, #30)."""

from moarcoal.documents import DocumentKind
from moarcoal.modules.work.entries import (
    KINDS,
    FirstWorkplace,
    UserInput,
    WageTaxCertificate,
    WorkEquipment,
)
from moarcoal.modules.work.pages import MODULE_KEY, entry_url, router
from moarcoal.modules.work.reading import read_in_wage_tax_certificate
from moarcoal.modules.work.values import FINDING_KINDS, VALUES, work_findings
from moarcoal.registration import ModuleRegistration

WAGE_TAX_CERTIFICATE_KEY = "wage_tax_certificate"  # Schlüssel der Dokumentart

WAGE_TAX_CERTIFICATE = DocumentKind(
    key=WAGE_TAX_CERTIFICATE_KEY,
    title="Lohnsteuerbescheinigung",
    has_period=True,
    read_in=read_in_wage_tax_certificate,
    unique_per_period=True,
)

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Arbeit",
    nav_label="Arbeit",
    nav_url="/arbeit",
    router=router,
    kinds=KINDS,
    values=VALUES,
    document_kinds=(WAGE_TAX_CERTIFICATE,),
    entry_url=entry_url,
    finding_kinds=FINDING_KINDS,
    findings=work_findings,
)

__all__ = [
    "REGISTRATION",
    "WAGE_TAX_CERTIFICATE",
    "FirstWorkplace",
    "UserInput",
    "WageTaxCertificate",
    "WorkEquipment",
]
