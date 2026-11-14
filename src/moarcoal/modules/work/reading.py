"""Einlese-Regel der Lohnsteuerbescheinigung (eDaten-HTML, `Belegart: VaSt_LStB`), ohne Claude.

Den Leser des HTML teilen alle Dokumentarten dieses Formats (`moarcoal.elster_html`). Hier steht,
welche Pfade für Anlage N Nr. 4 bis 7 gelten: Steuerklasse, Bruttoarbeitslohn, Lohnsteuer und
Solidaritätszuschlag. Das HTML enthält nur belegte Felder; was fehlt, bleibt leer (nie 0). Kommt
ein Pfad mehrfach vor (Wiederholgruppe, z. B. Steuerklassenwechsel im Jahr), ist nicht entschieden,
welcher Wert gilt; die Datei wird dann abgewiesen statt geraten.
"""

from pydantic import ValidationError

from moarcoal.documents import ReadInError
from moarcoal.elster_html import HtmlField, parse_elster_html
from moarcoal.modules.work.entries import WageTaxCertificate
from moarcoal.storage import Document, Entry
from moarcoal.values.model import parse_german_number

READER_VERSION = 1
BELEGART = "VaSt_LStB"

TAX_CLASS = "Besteuerungsmerkmal-ELStAM-Steuerklasse-Klasse"
GROSS_WAGES = "Besteuerungsgrund-BruttoArbLohn"
INCOME_TAX = "Besteuerungsgrund-LSteuer"
SOLI = "Besteuerungsgrund-Soli"


def _single(fields: list[HtmlField], path: str, name: str) -> HtmlField | None:
    found = [f for f in fields if f.path == f"{BELEGART}-{path}"]
    if len(found) > 1:
        raise ReadInError(
            f"{name} steht {len(found)}-mal in der Datei; welcher Wert gilt, ist offen."
        )
    return found[0] if found else None


def _cents(field: HtmlField, name: str) -> int:
    amount = parse_german_number(field.text)
    cents = None if amount is None else amount * 100
    if cents is None or cents != cents.to_integral_value() or cents < 0:
        raise ReadInError(f"{name}: „{field.text}“ ist kein Betrag in Euro und Cent.")
    return int(cents)


def _tax_class(field: HtmlField) -> int:
    if field.text not in {"1", "2", "3", "4", "5", "6"}:
        raise ReadInError(f"Steuerklasse: „{field.text}“ ist keine Steuerklasse von 1 bis 6.")
    return int(field.text)


def read_in_wage_tax_certificate(document: Document, content: bytes) -> list[Entry]:
    """Einlese-Regel der Dokumentart Lohnsteuerbescheinigung."""
    if document.period_start is None:
        raise ReadInError("Das Dokument hat keinen Bezugszeitraum.")
    parsed = parse_elster_html(content)
    if parsed.belegart != BELEGART:
        raise ReadInError(
            f"Die Datei ist keine Lohnsteuerbescheinigung (Belegart {BELEGART} fehlt im Kopf)."
        )
    year = document.period_start.year
    if parsed.year is not None and parsed.year != year:
        raise ReadInError(
            f"Die Lohnsteuerbescheinigung gehört zum Steuerjahr {parsed.year}, "
            f"eingetragen ist {year}."
        )
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
        )
    except ValidationError as error:
        raise ReadInError(
            "Ein Wert der Lohnsteuerbescheinigung liegt außerhalb des Bereichs."
        ) from error
    return [entry]
