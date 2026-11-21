"""Einlese-Regel der Lohnsteuerbescheinigung (eDaten-HTML, `Belegart: VaSt_LStB`), ohne Claude.

Den Leser des HTML teilen alle Dokumentarten dieses Formats (`modules/elster_html.py`). Hier steht,
welche Pfade für Anlage N Nr. 4 bis 7 gelten: Steuerklasse, Bruttoarbeitslohn, Lohnsteuer und
Solidaritätszuschlag. Das HTML enthält nur belegte Felder; was fehlt, bleibt leer (nie 0). Kommt
ein Pfad mehrfach vor (Wiederholgruppe, z. B. Steuerklassenwechsel im Jahr), ist nicht entschieden,
welcher Wert gilt; die Datei wird dann abgewiesen statt geraten.

Die Arbeitgeberleistungen laut Nr. 17 und 18 kamen in keiner bisher gesehenen Bescheinigung vor;
ihre Pfade sind darum unbekannt. Die Einlese-Regel kennt alle Pfade, die in echten Bescheinigungen
vorkamen (`KNOWN_PATHS`), und hält jeden anderen fest (`unrecognized`). Nur ohne solche Pfade steht
fest, dass die Bescheinigung Nr. 17 und 18 nicht nennt.
"""

from pydantic import ValidationError

from moarcoal.documents import DocumentKind, ReadInError
from moarcoal.modules.elster_html import HtmlField, parse_elster_document
from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.storage import Document, ReadInEntry
from moarcoal.values.model import parse_cents

READER_VERSION = 2  # 2: unbekannte Pfade festhalten (Nr. 17, 18)
TITLE = "Lohnsteuerbescheinigung"  # Titel der Dokumentart
BELEGART = "VaSt_LStB"

TAX_CLASS = "Besteuerungsmerkmal-ELStAM-Steuerklasse-Klasse"
GROSS_WAGES = "Besteuerungsgrund-BruttoArbLohn"
INCOME_TAX = "Besteuerungsgrund-LSteuer"
SOLI = "Besteuerungsgrund-Soli"

# Pfade aus echten Bescheinigungen 2025 (ohne `VaSt_LStB-` und Index); Werte bleiben lokal.
KNOWN_PATHS = frozenset(
    {
        "Allgemein-IdNr",
        "Allgemein-Name",
        "Allgemein-Vorname",
        "ArbGName",
        "Besteuerungsgrund-ArbgAnteilRenVers",
        "Besteuerungsgrund-ArbnAnteilArblVers",
        "Besteuerungsgrund-ArbnAnteilRenVers",
        "Besteuerungsgrund-BeitrPrKrankVers",
        GROSS_WAGES,
        INCOME_TAX,
        SOLI,
        "Besteuerungsgrund-StFreiGePflegVers",
        "Besteuerungsgrund-StFreiPrKrankVers",
        "Besteuerungsmerkmal-ELStAM-GueltigAb",
        "Besteuerungsmerkmal-ELStAM-Kirchensteuerabzug-Konfession",
        TAX_CLASS,
        "Dauer-Anfang",
        "Dauer-Ende",
        "Dauer-Jahr",
        "Eingangsdatum",
    }
)


def _single(fields: list[HtmlField], path: str, name: str) -> HtmlField | None:
    found = [f for f in fields if f.path == f"{BELEGART}-{path}"]
    if len(found) > 1:
        raise ReadInError(
            f"{name} steht {len(found)}-mal in der Datei; welcher Wert gilt, ist offen."
        )
    return found[0] if found else None


def _unrecognized(fields: list[HtmlField]) -> list[str]:
    """Die Pfade der Datei, die die Einlese-Regel nicht kennt, sortiert und ohne Dopplung."""
    prefix = f"{BELEGART}-"
    return sorted({f.path.removeprefix(prefix) for f in fields} - KNOWN_PATHS)


def _cents(field: HtmlField, name: str) -> int:
    cents = parse_cents(field.text)
    if cents is None or cents < 0:
        raise ReadInError(f"{name}: „{field.text}“ ist kein Betrag in Euro und Cent.")
    return cents


def _tax_class(field: HtmlField) -> int:
    if field.text not in {"1", "2", "3", "4", "5", "6"}:
        raise ReadInError(f"Steuerklasse: „{field.text}“ ist keine Steuerklasse von 1 bis 6.")
    return int(field.text)


def read_in_wage_tax_certificate(document: Document, content: bytes) -> list[ReadInEntry]:
    """Einlese-Regel der Dokumentart Lohnsteuerbescheinigung."""
    year, parsed = parse_elster_document(document, content, BELEGART, TITLE)
    fields = list(parsed.fields)
    tax_class = _single(fields, TAX_CLASS, "Steuerklasse")
    gross = _single(fields, GROSS_WAGES, "Bruttoarbeitslohn")
    income_tax = _single(fields, INCOME_TAX, "Lohnsteuer")
    soli = _single(fields, SOLI, "Solidaritätszuschlag")
    if gross is None:
        raise ReadInError(
            "Der Bruttoarbeitslohn fehlt in der Datei; keine Lohnsteuerbescheinigung?"
        )
    places = {
        key: f.data_name
        for key, f in (
            ("tax_class", tax_class),
            ("gross_wages", gross),
            ("income_tax", income_tax),
            ("soli", soli),
        )
        if f is not None
    }
    try:
        entry = WageTaxCertificate(
            owner=document.owner,
            document=document.address,
            year=year,
            reader_version=READER_VERSION,
            tax_class=None if tax_class is None else _tax_class(tax_class),
            gross_wages_cents=_cents(gross, "Bruttoarbeitslohn"),
            income_tax_cents=None if income_tax is None else _cents(income_tax, "Lohnsteuer"),
            soli_cents=None if soli is None else _cents(soli, "Solidaritätszuschlag"),
            places=places,
            unrecognized=_unrecognized(fields),
        )
    except ValidationError as error:
        raise ReadInError(
            "Ein Wert der Lohnsteuerbescheinigung liegt außerhalb des Bereichs."
        ) from error
    return [entry]


WAGE_TAX_CERTIFICATE = DocumentKind(
    key="wage_tax_certificate",
    title=TITLE,
    has_period=True,
    read_in=read_in_wage_tax_certificate,
    reader_version=READER_VERSION,
    unique_per_period=True,
)
