"""Modul Arbeit: Angaben zur Anlage N. Die Teile liegen in Unterordnern (`wage_tax`, `trips`,
`workplace`); hier werden sie zur einen Modulanmeldung gesammelt."""

from fastapi import APIRouter

from moarcoal.modules.work.common import MODULE_KEY
from moarcoal.modules.work.pages import router as pages_router
from moarcoal.modules.work.trips import entries as trip_entries
from moarcoal.modules.work.trips import values as trip_values
from moarcoal.modules.work.trips.entries import BusinessTrip, TripsConfirmation
from moarcoal.modules.work.trips.pages import router as trip_router
from moarcoal.modules.work.trips.places import PLACE_KINDS, Place
from moarcoal.modules.work.trips.reading import STATEMENT
from moarcoal.modules.work.wage_tax import entries as wage_tax_entries
from moarcoal.modules.work.wage_tax import values as wage_tax_values
from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.modules.work.wage_tax.reading import WAGE_TAX_CERTIFICATE
from moarcoal.modules.work.workplace import entries as workplace_entries
from moarcoal.modules.work.workplace import values as workplace_values
from moarcoal.modules.work.workplace.entries import FirstWorkplace, UserInput, WorkEquipment
from moarcoal.modules.work.workplace.forms import entry_url
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding

# Die Seite der Dienstreisen zuerst: ihre Adresse passt sonst auf `/arbeit/{art}/{kennung}`.
router = APIRouter()
router.include_router(trip_router)
router.include_router(pages_router)


def work_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    return [
        *workplace_values.equipment_findings(state, values, year),
        *trip_values.trip_findings(state, values, year),
    ]


REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Arbeit",
    nav_label="Arbeit",
    nav_url="/arbeit",
    icon="arbeit",
    router=router,
    kinds=workplace_entries.KINDS + wage_tax_entries.KINDS + trip_entries.KINDS + PLACE_KINDS,
    values=workplace_values.VALUES + wage_tax_values.VALUES + trip_values.VALUES,
    document_kinds=(WAGE_TAX_CERTIFICATE, STATEMENT),
    entry_url=entry_url,
    finding_kinds=workplace_values.FINDING_KINDS + trip_values.FINDING_KINDS,
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
