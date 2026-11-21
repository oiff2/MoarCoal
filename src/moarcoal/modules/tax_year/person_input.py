"""Eingaben zur Person im Steuerjahr: aus dem Formular eine Liste von Änderungen machen."""

from moarcoal.modules.tax_year.entries import YearPersonInput
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Delete, Put, entry_checksum


def current_person_input(state: ModuleState, year: int) -> YearPersonInput | None:
    """Die Eingabe zur Person des Nutzers im Jahr, falls es eine gibt."""
    return next((e for e in state.all(YearPersonInput) if e.year == year), None)


def year_person_input_changes(
    state: ModuleState, year: int, occupation: str, phone: str, in_this_return: str
) -> list[Change]:
    """Die Änderungen, die die Eingaben zur Person im Jahr ablegen.

    Leere Texte sind noch nicht angegeben; sind alle leer, wird die Eingabe zurückgenommen. Ob
    das Telefon eine Nummer ist, prüft der Schreibweg.
    """
    texts = {
        "occupation": occupation.strip() or None,
        "phone": phone.strip() or None,
        "in_this_return": in_this_return.strip() or None,
    }
    existing = current_person_input(state, year)
    if not any(texts.values()):
        return [Delete(existing.address, entry_checksum(existing))] if existing else []
    if existing is None:
        return [Put(YearPersonInput(owner=state.user, year=year).model_copy(update=texts))]
    return [Put(existing.model_copy(update=texts), expected=entry_checksum(existing))]
