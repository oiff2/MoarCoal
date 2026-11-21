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


def form_name(form: str) -> str:
    """Der Name der Anlage zum Anzeigen; eine unbekannte heißt „Anlage <Schlüssel>“."""
    return FORM_NAMES.get(form, f"Anlage {form}")


def protocol_page(form: str, segment: str) -> str:
    """Der Seitentitel zum ersten Pfadteil eines Protokollfelds; unbekannt: der Pfadteil selbst."""
    return PROTOCOL_PAGES.get(form, {}).get(segment, segment)


def form_rank(form: str) -> tuple[int, str]:
    """Sortierschlüssel: Reihenfolge der Formularliste, unbekannte Anlagen danach."""
    return (FORM_ORDER.index(form) if form in FORM_ORDER else len(FORM_ORDER), form)
