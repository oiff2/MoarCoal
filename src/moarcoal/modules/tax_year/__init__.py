"""Modul Steuerjahr: Übertragungsprotokoll einlesen, Werte Feldern der Anlage N zuordnen."""

from functools import partial

from moarcoal.documents import DocumentKind
from moarcoal.modules.tax_year.anlage_n import FORMS, Forms, values_for
from moarcoal.modules.tax_year.comparison import (
    FINDING_KINDS,
    module_findings,
    snapshot_on_filing,
)
from moarcoal.modules.tax_year.entries import (
    KINDS,
    TRANSFER_PROTOCOL_KEY,
    ProtocolLine,
    ProtocolReading,
)
from moarcoal.modules.tax_year.pages import MODULE_KEY, entry_url, router
from moarcoal.modules.tax_year.reading import read_in_protocol
from moarcoal.registration import ModuleRegistration


def transfer_protocol(forms: Forms = FORMS) -> DocumentKind:
    """Die Dokumentart Übertragungsprotokoll; beim Aufnehmen friert sie die Felder von `forms`
    als Schnappschuss der Abgabe ein."""
    return DocumentKind(
        key=TRANSFER_PROTOCOL_KEY,
        title="Übertragungsprotokoll",
        has_period=True,
        read_in=read_in_protocol,
        after_take_in=partial(snapshot_on_filing, forms=forms),
    )


TRANSFER_PROTOCOL = transfer_protocol()


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
        document_kinds=(transfer_protocol(forms),),
        finding_kinds=FINDING_KINDS,
        findings=partial(module_findings, forms=forms),
    )


REGISTRATION = registration()

__all__ = ["REGISTRATION", "registration", "TRANSFER_PROTOCOL", "ProtocolLine", "ProtocolReading"]
