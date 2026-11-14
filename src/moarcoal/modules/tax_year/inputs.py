"""Eingaben zu Eintippfeldern der Anlage: aus dem Formular eine Liste von Änderungen machen."""

from moarcoal.modules.tax_year.entries import FormInput
from moarcoal.modules.tax_year.fields import FormField
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Delete, Put, entry_checksum


def current_input(state: ModuleState, year: int, field: FormField) -> FormInput | None:
    """Die Eingabe des Nutzers zu `field` im Jahr, falls es eine gibt."""
    return next(
        (e for e in state.all(FormInput) if (e.year, e.elster_id) == (year, field.elster_id)),
        None,
    )


def changes_for_input(
    state: ModuleState, year: int, field: FormField, text: str
) -> tuple[list[Change], str | None]:
    """Die Änderungen, die `text` als Eingabe zu `field` ablegen, oder der Grund der Ablehnung.

    Leerer Text nimmt die Eingabe zurück; dann ist das Feld wieder noch nicht berechenbar.
    """
    if field.typed is None or field.elster_id is None:
        return [], "Dieses Feld nimmt keine Eingabe."
    text = text.strip()
    existing = current_input(state, year, field)
    if not text:
        return ([Delete(existing.address, entry_checksum(existing))] if existing else []), None
    if (reason := field.typed.check(text)) is not None:
        return [], reason
    if existing is None:
        entry = FormInput(owner=state.user, year=year, elster_id=field.elster_id, content=text)
        return [Put(entry)], None
    updated = existing.model_copy(update={"content": text})
    return [Put(updated, expected=entry_checksum(existing))], None
