"""Die Anlagen der Steuererklärung, wie das Übertragungsprotokoll sie nennt, mit Anzeigename,
Reihenfolge der Formularliste in Mein ELSTER und den Seitentiteln der vorläufigen Struktur."""

FORM_ORDER = ("ESt1A", "VOR", "SA", "N", "KAP", "V")  # Reihenfolge in Mein ELSTER
FORM_NAMES = {
    "ESt1A": "Hauptvordruck ESt 1 A",
    "VOR": "Anlage Vorsorgeaufwand",
    "SA": "Anlage Sonderausgaben",
    "N": "Anlage N",
    "KAP": "Anlage KAP",
    "V": "Anlage V",
}

PROTOCOL_PAGES: dict[str, dict[str, str]] = {
    # Seite in Mein ELSTER je erstem Pfadteil eines Felds im Übertragungsprotokoll, solange die
    # Anlage keine gespeicherte Struktur hat (#164). Mit Nummer: Titel aus Mein ELSTER (Kohlebau,
    # Katalog 2025); ohne Nummer: Überschrift im amtlichen Vordruck 2025.
    "ESt1A": {
        "Art_Erkl": "Art der Erklärung",
        "Allg": "Allgemeine Angaben",
        "Erg_Ang": "Ergänzende Angaben zur Steuererklärung",
    },
    "VOR": {
        "AVor": "1 - Beiträge zur Altersvorsorge",
        "Beitr_g_KV_PV_Inl": "2 - Beiträge zur inländischen gesetzlichen Kranken- und "
        "Pflegeversicherung",
        "Beitr_p_KV_PV_Inl": "3 - Beiträge zur inländischen privaten Kranken- und "
        "Pflegeversicherung",
        "Stfr_AG_Zusch": "5 - Steuerfreie Arbeitgeberzuschüsse",
        "Weit_Sons_VorAW": "7 - Weitere sonstige Vorsorgeaufwendungen",
    },
    "SA": {
        "KiSt": "Kirchensteuer",
    },
    "KAP": {
        "Ant": "1 - Anträge",
        "KapErt_inl_StAbz": "3 - Kapitalerträge, die dem inländischen Steuerabzug unterlegen haben",
        "Sp_PB": "4 - Sparer-Pauschbetrag",
        "St_Abz_Betr_Inl_u_Inv_Ert": "8 - Steuerabzugsbeträge zu Erträgen in den Zeilen 7 bis 23 "
        "und zu Investmenterträgen laut Anlage KAP-INV",
    },
}


PROTOCOL_UNITS: dict[str, str] = {
    # Einheit je E-Kennung für Felder ohne gespeicherte Struktur (das Protokoll druckt keine).
    # Aus dem Kohlebau-Katalog 2025 (Einheit euro, euro_cent, flaeche); bis gespeicherte Seiten
    # sie liefern (#164).
    # KAP
    "E1900701": "€",
    "E1900901": "€",
    "E1901502": "€",
    "E1901401": "€",
    "E1901402": "€",
    "E1904701": "€",
    "E1904901": "€",
    "E1904801": "€",
    "E1905001": "€",
    "E1905101": "€",
    # SA
    "E0108004": "€",  # Kirchensteuer gezahlt, Einzelangabe zur Summe E0107601
    "E0107601": "€",
    "E0107602": "€",
    # VOR
    "E2001802": "€",  # Betrag je Versicherung, Einzelangabe zur Summe E2001803
    "E2000401": "€",
    "E2000701": "€",
    "E2000801": "€",
    "E2001203": "€",
    "E2001405": "€",
    "E2001505": "€",
    "E2001605": "€",
    "E2001705": "€",
    "E2003104": "€",
    "E2003202": "€",
    "E2003302": "€",
    "E2003502": "€",
    "E2003705": "€",
    "E2003807": "€",
    "E2003907": "€",
    "E2004403": "€",
    "E2001803": "€",
}


def form_name(form: str) -> str:
    """Der Name der Anlage zum Anzeigen; eine unbekannte heißt „Anlage <Schlüssel>“."""
    return FORM_NAMES.get(form, f"Anlage {form}")


def protocol_page(form: str, segment: str) -> str:
    """Der Seitentitel zum ersten Pfadteil eines Protokollfelds; unbekannt: der Pfadteil selbst."""
    return PROTOCOL_PAGES.get(form, {}).get(segment, segment)


def protocol_unit(elster_id: str) -> str:
    """Die Einheit eines Protokollfelds ohne gespeicherte Struktur; unbekannt: leer."""
    return PROTOCOL_UNITS.get(elster_id, "")


def form_rank(form: str) -> tuple[int, str]:
    """Sortierschlüssel: Reihenfolge der Formularliste, unbekannte Anlagen danach."""
    return (FORM_ORDER.index(form) if form in FORM_ORDER else len(FORM_ORDER), form)
