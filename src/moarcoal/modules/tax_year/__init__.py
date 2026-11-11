"""Modul Steuerjahr: nimmt das Übertragungsprotokoll auf und liest es ein (Durchstich, #33)."""

from moarcoal.documents import DocumentKind
from moarcoal.modules.tax_year.entries import (
    KINDS,
    TRANSFER_PROTOCOL_KEY,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.modules.tax_year.pages import MODULE_KEY, router
from moarcoal.modules.tax_year.reading import read_in_protocol
from moarcoal.registration import ModuleRegistration

TRANSFER_PROTOCOL = DocumentKind(
    key=TRANSFER_PROTOCOL_KEY,
    title="Übertragungsprotokoll",
    has_period=True,
    read_in=read_in_protocol,
)

REGISTRATION = ModuleRegistration(
    key=MODULE_KEY,
    area_name="Steuerjahr",
    nav_label="Steuerjahr",
    nav_url="/steuerjahr",
    router=router,
    kinds=KINDS,
    document_kinds=(TRANSFER_PROTOCOL,),
)

__all__ = ["REGISTRATION", "TRANSFER_PROTOCOL", "ProtocolLine", "ProtocolReading"]
