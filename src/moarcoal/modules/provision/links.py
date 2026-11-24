"""Adressen der Seite Vorsorge; nur hier gebaut (Routen und Vorlagen nehmen sie von hier)."""


def provision_url(year: int) -> str:
    """Die Seite Vorsorge für ein Steuerjahr."""
    return f"/vorsorge?jahr={year}"


def meaning_url(agreement_id: str) -> str:
    """Die Steuerliche Bedeutung eines Vertrags setzen oder entfernen (POST)."""
    return f"/vorsorge/bedeutung/{agreement_id}"
