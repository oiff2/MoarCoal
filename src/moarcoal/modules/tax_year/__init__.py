"""Modul Steuerjahr: Übertragungsprotokoll einlesen, Werte Feldern der Anlage N zuordnen,
EStB auslesen und mit dem Schnappschuss der Abgabe abgleichen."""

from collections.abc import Mapping
from functools import partial

from moarcoal.documents import DocumentKind
from moarcoal.modules.tax_year.anlage_n import FORMS, STRUCTURES, Forms, values_for
from moarcoal.modules.tax_year.assessment import ASSESSMENT
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
from moarcoal.modules.tax_year.structure import FormStructure
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
        unique_per_period=True,
    )


TRANSFER_PROTOCOL = transfer_protocol()


def registration(
    forms: Forms = FORMS, structures: Mapping[int, FormStructure] = STRUCTURES
) -> ModuleRegistration:
    """Die Modulanmeldung über den Feldern `forms` und den Strukturen `structures`; Tests geben
    einen eigenen Katalog vor."""
    return ModuleRegistration(
        key=MODULE_KEY,
        area_name="Steuerjahr",
        nav_label="Steuerjahr",
        nav_url="/steuerjahr",
        router=router,
        entry_url=entry_url,
        kinds=KINDS,
        values=values_for(forms),
        document_kinds=(transfer_protocol(forms), ASSESSMENT),
        finding_kinds=FINDING_KINDS,
        findings=partial(module_findings, forms=forms, structures=structures),
    )


REGISTRATION = registration()

__all__ = [
    "ASSESSMENT",
    "REGISTRATION",
    "registration",
    "TRANSFER_PROTOCOL",
    "ProtocolLine",
    "ProtocolReading",
]
