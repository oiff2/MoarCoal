"""Adressen der Seite Vorsorge; nur hier gebaut (Routen und Vorlagen nehmen sie von hier)."""


def provision_url(year: int) -> str:
    """Die Seite Vorsorge für ein Steuerjahr."""
    return f"/vorsorge?jahr={year}"


def meaning_url(agreement_id: str) -> str:
    """Die Steuerliche Bedeutung eines Vertrags setzen oder entfernen (POST)."""
    return f"/vorsorge/bedeutung/{agreement_id}"


def contribution_url(agreement_id: str) -> str:
    """Den Jahresbeitrag eines Vertrags erfassen oder ändern (POST)."""
    return f"/vorsorge/jahresbeitrag/{agreement_id}"


def contribution_delete_url(agreement_id: str) -> str:
    """Den Jahresbeitrag eines Vertrags löschen (POST)."""
    return f"/vorsorge/jahresbeitrag/{agreement_id}/loeschen"
