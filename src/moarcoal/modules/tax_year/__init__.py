"""Modul Steuerjahr: Übertragungsprotokoll einlesen, Werte Feldern der Anlage N zuordnen."""

from functools import partial

from moarcoal.documents import DocumentKind
from moarcoal.modules.tax_year.anlage_n import FORMS, Forms, values_for
from moarcoal.modules.tax_year.comparison import FINDING_KINDS, protocol_findings
from moarcoal.modules.tax_year.entries import (
    KINDS,
    TRANSFER_PROTOCOL_KEY,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.modules.tax_year.pages import MODULE_KEY, entry_url, router
from moarcoal.modules.tax_year.reading import read_in_protocol
from moarcoal.registration import ModuleRegistration

TRANSFER_PROTOCOL = DocumentKind(
    key=TRANSFER_PROTOCOL_KEY,
    title="Übertragungsprotokoll",
    has_period=True,
    read_in=read_in_protocol,
)


def registration(forms: Forms = FORMS) -> ModuleRegistration:
    """Die Modulanmeldung über den Feldern `forms`; Tests geben einen eigenen Katalog vor."""
    return ModuleRegistration(
        key=MODULE_KEY,
        area_name="Steuerjahr",
        nav_label="Steuerjahr",
        nav_url="/steuerjahr",
        router=router,
        entry_url=entry_url,
        kinds=KINDS,
        values=values_for(forms),
        document_kinds=(TRANSFER_PROTOCOL,),
        finding_kinds=FINDING_KINDS,
        findings=partial(protocol_findings, forms=forms),
    )


REGISTRATION = registration()

__all__ = ["REGISTRATION", "registration", "TRANSFER_PROTOCOL", "ProtocolLine", "ProtocolReading"]
