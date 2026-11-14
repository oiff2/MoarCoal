"""Dokumentart Einkommensteuerbescheid (EStB): die Auslese-Vorlage mit den gedruckten Positionen.

Der EStB wird nicht eingelesen, sondern von Claude ausgelesen und vom Nutzer bestätigt
(`proposals`). Die Vorlage nennt die gedruckten Positionen mit ihrer Bezeichnung im EStB; welche
Position welchem Feld der Anlage N entspricht, steht am Feld (`FormField.assessment`). Positionen
ohne Feld (Arbeitnehmer-Pauschbetrag, Einkünfte, Entfernungspauschale) kommen mit, weil der EStB
sie druckt; sie haben kein Gegenstück im Schnappschuss.

Doppelt gedruckte Bezeichnungen tragen ihren Block in Klammern (`erkenntnisse.md`): „Einkünfte“
steht im EStB für Arbeit und für Vermietung und Verpachtung.
"""

from moarcoal.documents import DocumentKind
from moarcoal.extraction_template import ExtractionTemplate, TemplateField
from moarcoal.storage import Document, Entry

ASSESSMENT_KEY = "assessment"  # Schlüssel der Dokumentart

GROSS_WAGES = "gross_wages"
EMPLOYEE_ALLOWANCE = "employee_allowance"
COMMUTE_DAYS = "commute_days"
COMMUTE_KM = "commute_km"
COMMUTE_ALLOWANCE = "commute_allowance"
MEAL_ALLOWANCE = "meal_allowance"
BUSINESS_TRAVEL = "business_travel"
EMPLOYMENT_INCOME = "employment_income"
INCOME_TAX_WITHHELD = "income_tax_withheld"
SOLI_WITHHELD = "soli_withheld"

TEMPLATE = ExtractionTemplate(
    1,
    (
        TemplateField(
            GROSS_WAGES,
            "Bruttoarbeitslohn",
            "EUR",
            "Block „Einkünfte aus nichtselbständiger Arbeit“, Zeile Bruttoarbeitslohn",
        ),
        TemplateField(
            EMPLOYEE_ALLOWANCE,
            "Arbeitnehmer-Pauschbetrag",
            "EUR",
            "Block „Einkünfte aus nichtselbständiger Arbeit“, unter „ab“; das gedruckte Minus "
            "ignorieren",
        ),
        TemplateField(
            COMMUTE_DAYS,
            "Wege zwischen Wohnung und erster Tätigkeitsstätte (Anzahl Tage)",
            "Tage",
            "Zahl vor „Tage x“ in der Zeile „Entfernungspauschale für … Tage“",
        ),
        TemplateField(
            COMMUTE_KM,
            "Wege zwischen Wohnung und erster Tätigkeitsstätte (einfache Entfernung)",
            "km",
            "Zahl vor „km“ in der Zeile „Tage x … km“",
        ),
        TemplateField(
            COMMUTE_ALLOWANCE,
            "Entfernungspauschale (insgesamt)",
            "EUR",
            "Zeile „insgesamt“ unter „Wege zwischen Wohnung und erster Tätigkeitsstätte“; "
            "das gedruckte Minus ignorieren",
        ),
        TemplateField(
            MEAL_ALLOWANCE,
            "Tagespauschale",
            "EUR",
            "Block „Werbungskosten“; das gedruckte Minus ignorieren",
        ),
        TemplateField(
            BUSINESS_TRAVEL,
            "Reisekosten bei Auswärtstätigkeiten",
            "EUR",
            "Block „Werbungskosten“; das gedruckte Minus ignorieren",
        ),
        TemplateField(
            EMPLOYMENT_INCOME,
            "Einkünfte (Einkünfte aus nichtselbständiger Arbeit)",
            "EUR",
            "Zeile „Einkünfte“ im Block „Einkünfte aus nichtselbständiger Arbeit“, nicht die "
            "Zeile aus „Vermietung und Verpachtung“",
        ),
        TemplateField(
            INCOME_TAX_WITHHELD,
            "Abzug vom Lohn (Einkommensteuer)",
            "EUR",
            "Tabelle am Anfang, Zeile „Abzug vom Lohn“, Spalte Einkommensteuer; das gedruckte "
            "Minus ignorieren",
        ),
        TemplateField(
            SOLI_WITHHELD,
            "Abzug vom Lohn (Solidaritätszuschlag)",
            "EUR",
            "Tabelle am Anfang, Zeile „Abzug vom Lohn“, Spalte Solidaritätszuschlag; das "
            "gedruckte Minus ignorieren",
        ),
    ),
)


def _no_read_in(document: Document, content: bytes) -> list[Entry]:
    return []  # der EStB wird nur ausgelesen, nicht eingelesen


ASSESSMENT = DocumentKind(
    key=ASSESSMENT_KEY,
    title="Einkommensteuerbescheid (EStB)",
    has_period=True,
    read_in=_no_read_in,
    extraction_template=TEMPLATE,
    unique_per_period=True,
)
