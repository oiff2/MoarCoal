"""Adressen der Seiten des Steuerjahrs, für Befunde und Verweise außerhalb der Routen-Angaben."""


def protocol_url(reading_id: str, data_name: str = "") -> str:
    """Seite eines eingelesenen Protokolls, auf Wunsch mit Sprung zur Zeile."""
    base = f"/steuerjahr/uebertragungsprotokolle/{reading_id}"
    return f"{base}#{data_name}" if data_name else base


def anlage_url(slug: str, year: int, page: str = "") -> str:
    """Die Anlage mit dem Adressteil `slug` im Jahr; ohne `page` ihre erste Seite."""
    base = f"/steuerjahr/anlage-{slug}/{year}"
    return f"{base}/{page}" if page else base
