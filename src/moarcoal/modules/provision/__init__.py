"""Modul Vorsorge: Beiträge zu Versicherungen und Altersvorsorge (Anlage Vorsorgeaufwand). Dieser
Teil: die Seite je Steuerjahr mit den Verträgen und ihrer Steuerlichen Bedeutung."""

from moarcoal.modules.provision.common import MODULE_KEY
from moarcoal.modules.provision.entries import KINDS, AgreementMeaning, TaxMeaning
from moarcoal.modules.provision.pages import router
from moarcoal.registration import ModuleRegistration

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Vorsorge",
    nav_label="Vorsorge",
    nav_url="/vorsorge",
    router=router,
    kinds=KINDS,
)

__all__ = ["REGISTRATION", "AgreementMeaning", "TaxMeaning"]
