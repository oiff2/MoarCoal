"""Modul Arbeit: Angaben zur Anlage N von Hand erfassen (Durchstich, #30)."""

from moarcoal.modules.work.entries import KINDS, FirstWorkplace, UserInput, WorkEquipment
from moarcoal.modules.work.pages import MODULE_KEY, router
from moarcoal.registration import ModuleRegistration

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Arbeit",
    nav_label="Arbeit",
    nav_url="/arbeit",
    router=router,
    kinds=KINDS,
)

__all__ = ["REGISTRATION", "FirstWorkplace", "UserInput", "WorkEquipment"]
