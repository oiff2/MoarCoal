"""Modul Arbeit: Angaben zur Anlage N von Hand erfassen (Durchstich, #30)."""

from moarcoal.modules.work.entries import KINDS, FirstWorkplace, UserInput, WorkEquipment
from moarcoal.modules.work.pages import MODULE_KEY, entry_url, router
from moarcoal.modules.work.values import FINDING_KINDS, VALUES, work_findings
from moarcoal.registration import ModuleRegistration

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Arbeit",
    nav_label="Arbeit",
    nav_url="/arbeit",
    router=router,
    kinds=KINDS,
    values=VALUES,
    entry_url=entry_url,
    finding_kinds=FINDING_KINDS,
    findings=work_findings,
)

__all__ = ["REGISTRATION", "FirstWorkplace", "UserInput", "WorkEquipment"]
