"""Modul Steuerjahr: die Anlagen eines Jahrs wie in Mein ELSTER abbilden, Übertragungsprotokoll
einlesen, Werten Felder der Anlagen zuordnen, EStB auslesen und mit dem Schnappschuss der Abgabe
abgleichen."""

from collections.abc import Sequence
from functools import partial

from moarcoal.documents import DocumentKind
from moarcoal.modules.tax_year.anlage_n import ANLAGEN
from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.assessment import ASSESSMENT
from moarcoal.modules.tax_year.comparison import FINDING_KINDS, module_findings
from moarcoal.modules.tax_year.entries import (
    MODULE_KEY,
    TRANSFER_PROTOCOL_KEY,
    ProtocolLine,
    ProtocolReading,
    kinds,
)
from moarcoal.modules.tax_year.inputs import input_problem
from moarcoal.modules.tax_year.pages import entry_url, router_for
from moarcoal.modules.tax_year.reading import READER_VERSION, TITLE, read_in_protocol
from moarcoal.modules.tax_year.snapshot_check import snapshot_on_filing
from moarcoal.registration import ModuleRegistration


def transfer_protocol(anlagen: Sequence[Anlage] = ANLAGEN) -> DocumentKind:
    """Die Dokumentart Übertragungsprotokoll; beim Aufnehmen friert sie die berechneten Felder
    aller `anlagen` als Schnappschuss der Abgabe ein."""
    return DocumentKind(
        key=TRANSFER_PROTOCOL_KEY,
        title=TITLE,
        has_period=True,
        read_in=read_in_protocol,
        reader_version=READER_VERSION,
        after_take_in=partial(snapshot_on_filing, anlagen=anlagen),
        unique_per_period=True,
    )


TRANSFER_PROTOCOL = transfer_protocol()


def registration(anlagen: Sequence[Anlage] = ANLAGEN) -> ModuleRegistration:
    """Die Modulanmeldung über den `anlagen` (Katalog, Struktur, Werte je Anlage); Tests geben
    eigene vor."""
    return ModuleRegistration(
        key=MODULE_KEY,
        area_name="Steuerjahr",
        nav_label="Steuerjahr",
        nav_url="/steuerjahr",
        icon="steuerjahr",
        router=router_for(anlagen),
        entry_url=entry_url,
        kinds=kinds(partial(input_problem, anlagen)),
        values=tuple(v for anlage in anlagen for v in anlage.define_values(anlage.forms)),
        document_kinds=(transfer_protocol(anlagen), ASSESSMENT),
        finding_kinds=FINDING_KINDS,
        findings=partial(module_findings, anlagen=anlagen),
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
