"""Modul Arbeit: Angaben zur Anlage N von Hand erfassen (Durchstich, #30)."""

from fastapi import APIRouter

from moarcoal.documents import DocumentKind
from moarcoal.modules.work.entries import (
    KINDS,
    BusinessTrip,
    FirstWorkplace,
    TripsConfirmation,
    UserInput,
    WageTaxCertificate,
    WorkEquipment,
)
from moarcoal.modules.work.pages import MODULE_KEY, entry_url
from moarcoal.modules.work.pages import router as pages_router
from moarcoal.modules.work.places import PLACE_KINDS, Place
from moarcoal.modules.work.reading import read_in_wage_tax_certificate
from moarcoal.modules.work.trip_pages import router as trip_router
from moarcoal.modules.work.trip_reading import STATEMENT
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

# Die Seite der Dienstreisen zuerst: ihre Adresse passt sonst auf `/arbeit/{art}/{kennung}`.
router = APIRouter()
router.include_router(trip_router)
router.include_router(pages_router)

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Arbeit",
    nav_label="Arbeit",
    nav_url="/arbeit",
    router=router,
    kinds=KINDS + PLACE_KINDS,
    values=VALUES,
    document_kinds=(WAGE_TAX_CERTIFICATE, STATEMENT),
    entry_url=entry_url,
    finding_kinds=FINDING_KINDS,
    findings=work_findings,
)

__all__ = [
    "REGISTRATION",
    "WAGE_TAX_CERTIFICATE",
    "BusinessTrip",
    "FirstWorkplace",
    "Place",
    "TripsConfirmation",
    "UserInput",
    "WageTaxCertificate",
    "WorkEquipment",
]
