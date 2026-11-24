"""Einlese-Regel der Lohnsteuerbescheinigung (eDaten-HTML, `Belegart: VaSt_LStB`), ohne Claude.

Den Leser des HTML teilen alle Dokumentarten dieses Formats (`modules/elster_html.py`). Hier steht,
welche Pfade für Anlage N Nr. 4 bis 7 gelten (Steuerklasse, Bruttoarbeitslohn, Lohnsteuer und
Solidaritätszuschlag) und für Nr. 22 a/b, 23 a/b, 24 b, 24 c und 27 der Lohnsteuerbescheinigung
(Beiträge zur Vorsorge, Anlage Vorsorgeaufwand). Nr. 24 a, 25 und 26 liest sie nicht: ihre Pfade
sind unbekannt (`BeitrPrKrankVers` ist keiner davon); ohne unbekannte Pfade in der Datei gelten
sie wie Nr. 17 und 18 als nicht bescheinigt. Das HTML enthält nur belegte Felder; was
fehlt, bleibt leer (nie 0). Kommt ein Pfad mehrfach vor (Wiederholgruppe, z. B. Steuerklassenwechsel
im Jahr), ist nicht entschieden, welcher Wert gilt; die Datei wird dann abgewiesen statt geraten.

Die Posten laut Nr. 17, 18, 24 a, 25 und 26 kamen in keiner bisher gesehenen Bescheinigung vor;
ihre Pfade sind darum unbekannt. Die Einlese-Regel kennt alle Pfade, die in echten Bescheinigungen
vorkamen (`KNOWN_PATHS`), und hält jeden anderen fest (`unrecognized`). Nur ohne solche Pfade steht
fest, dass die Bescheinigung Nr. 17, 18, 24 a, 25 und 26 nicht nennt.
"""

from pydantic import ValidationError

from moarcoal.documents import DocumentKind, ReadInError
from moarcoal.modules.elster_html import (
    HtmlField,
    parse_elster_document,
    read_cents,
    single_field,
    unrecognized_paths,
)
from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.storage import Document, ReadInEntry

READER_VERSION = 3  # 2: unbekannte Pfade festhalten (Nr. 17, 18); 3: Nr. 22 bis 24, 27
TITLE = "Lohnsteuerbescheinigung"  # Titel der Dokumentart
BELEGART = "VaSt_LStB"

TAX_CLASS = "Besteuerungsmerkmal-ELStAM-Steuerklasse-Klasse"
GROSS_WAGES = "Besteuerungsgrund-BruttoArbLohn"
INCOME_TAX = "Besteuerungsgrund-LSteuer"
SOLI = "Besteuerungsgrund-Soli"
EMPLOYER_PENSION = "Besteuerungsgrund-ArbgAnteilRenVers"  # Nr. 22 a/b
EMPLOYEE_PENSION = "Besteuerungsgrund-ArbnAnteilRenVers"  # Nr. 23 a/b
SUBSIDY_PRIVATE_HEALTH = "Besteuerungsgrund-StFreiPrKrankVers"  # Nr. 24 b
SUBSIDY_CARE = "Besteuerungsgrund-StFreiGePflegVers"  # Nr. 24 c
UNEMPLOYMENT = "Besteuerungsgrund-ArbnAnteilArblVers"  # Nr. 27

# Pfade aus echten Bescheinigungen 2025 (ohne `VaSt_LStB-` und Index); Werte bleiben lokal.
KNOWN_PATHS = frozenset(
    {
        "Allgemein-IdNr",
        "Allgemein-Name",
        "Allgemein-Vorname",
        "ArbGName",
        EMPLOYER_PENSION,
        UNEMPLOYMENT,
        EMPLOYEE_PENSION,
        "Besteuerungsgrund-BeitrPrKrankVers",
        GROSS_WAGES,
        INCOME_TAX,
        SOLI,
        SUBSIDY_CARE,
        SUBSIDY_PRIVATE_HEALTH,
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
    return single_field(fields, BELEGART, path, name)


def _tax_class(field: HtmlField) -> int:
    if field.text not in {"1", "2", "3", "4", "5", "6"}:
        raise ReadInError(f"Steuerklasse: „{field.text}“ ist keine Steuerklasse von 1 bis 6.")
    return int(field.text)


# Angabe -> (Pfad, Name in Meldungen): die Beträge der Vorsorge, je Feld von `WageTaxCertificate`
VORSORGE = {
    "employer_pension": (EMPLOYER_PENSION, "Arbeitgeberanteil Rentenversicherung (Nr. 22)"),
    "employee_pension": (EMPLOYEE_PENSION, "Arbeitnehmeranteil Rentenversicherung (Nr. 23)"),
    "subsidy_private_health": (SUBSIDY_PRIVATE_HEALTH, "Zuschuss private Krankenversicherung"),
    "subsidy_care": (SUBSIDY_CARE, "Zuschuss gesetzliche Pflegeversicherung"),
    "unemployment": (UNEMPLOYMENT, "Arbeitslosenversicherung (Nr. 27)"),
}


def _vorsorge_cents(found: dict[str, HtmlField | None], key: str) -> int | None:
    field = found[key]
    return None if field is None else read_cents(field, VORSORGE[key][1])


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
    vorsorge = {key: _single(fields, path, name) for key, (path, name) in VORSORGE.items()}
    places = {
        key: f.data_name
        for key, f in (
            ("tax_class", tax_class),
            ("gross_wages", gross),
            ("income_tax", income_tax),
            ("soli", soli),
            *vorsorge.items(),
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
            gross_wages_cents=read_cents(gross, "Bruttoarbeitslohn"),
            income_tax_cents=None if income_tax is None else read_cents(income_tax, "Lohnsteuer"),
            soli_cents=None if soli is None else read_cents(soli, "Solidaritätszuschlag"),
            employer_pension_cents=_vorsorge_cents(vorsorge, "employer_pension"),
            employee_pension_cents=_vorsorge_cents(vorsorge, "employee_pension"),
            subsidy_private_health_cents=_vorsorge_cents(vorsorge, "subsidy_private_health"),
            subsidy_care_cents=_vorsorge_cents(vorsorge, "subsidy_care"),
            unemployment_cents=_vorsorge_cents(vorsorge, "unemployment"),
            places=places,
            unrecognized=unrecognized_paths(fields, BELEGART, KNOWN_PATHS),
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
