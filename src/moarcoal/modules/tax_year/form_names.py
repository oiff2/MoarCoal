"""Die Anlagen der Steuererklärung, wie das Übertragungsprotokoll sie nennt, mit Anzeigename und
Reihenfolge der Formularliste in Mein ELSTER."""

FORM_ORDER = ("ESt1A", "VOR", "SA", "N", "KAP", "V")  # Reihenfolge in Mein ELSTER
FORM_NAMES = {
    "ESt1A": "ESt 1 A",
    "VOR": "Anlage Vorsorgeaufwand",
    "SA": "Anlage Sonderausgaben",
    "N": "Anlage N",
    "KAP": "Anlage KAP",
    "V": "Anlage V",
}


def form_name(form: str) -> str:
    """Der Name der Anlage zum Anzeigen; eine unbekannte heißt „Anlage <Schlüssel>“."""
    return FORM_NAMES.get(form, f"Anlage {form}")


def form_rank(form: str) -> tuple[int, str]:
    """Sortierschlüssel: Reihenfolge der Formularliste, unbekannte Anlagen danach."""
    return (FORM_ORDER.index(form) if form in FORM_ORDER else len(FORM_ORDER), form)
