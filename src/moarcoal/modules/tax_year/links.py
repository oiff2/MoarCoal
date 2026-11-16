"""Adressen der Seiten des Steuerjahrs, für Befunde und Verweise außerhalb der Routen-Angaben."""


def protocol_url(reading_id: str, data_name: str = "") -> str:
    """Seite eines eingelesenen Protokolls, auf Wunsch mit Sprung zur Zeile."""
    base = f"/steuerjahr/uebertragungsprotokolle/{reading_id}"
    return f"{base}#{data_name}" if data_name else base


def anlage_n_url(year: int) -> str:
    """Die erste Seite der Anlage N des Jahrs."""
    return f"/steuerjahr/anlage-n/{year}"
