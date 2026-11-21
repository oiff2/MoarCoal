"""Vorgaben, die mehrere Teile der App brauchen, ohne dass ein Modul das andere importiert."""

# Durchstich: ein fester Nutzer; Nutzerliste und Nutzerwechsel kommen mit dem Prototyp (#62).
DEFAULT_USER = "ich"

# Platzhalter, bis das globale Jahr gebaut ist („Jahr global, je Seite übersteuerbar“ im
# Grundgerüst); dann ersetzt die Auswahl diese Vorgabe.
DEFAULT_YEAR = 2025

# Der einzige Jahresbereich: Jahre außerhalb gelten als Eingabefehler.
MIN_YEAR = 2000
MAX_YEAR = 2100


def year_of(text: str, *, in_range: bool = False) -> int | None:
    """Das Jahr als ganze Zahl (Randleerzeichen egal); `None`, wenn `text` keine ist, mit
    `in_range` auch, wenn sie außerhalb von `MIN_YEAR` bis `MAX_YEAR` liegt."""
    try:
        year = int(text.strip())
    except ValueError:
        return None
    return year if not in_range or MIN_YEAR <= year <= MAX_YEAR else None
