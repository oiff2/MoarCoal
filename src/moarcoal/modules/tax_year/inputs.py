"""Eingaben zu Eintippfeldern der Anlage: aus dem Formular eine Liste von Änderungen machen."""

from moarcoal.modules.tax_year.entries import FormInput
from moarcoal.modules.tax_year.fields import FormField, Forms
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Delete, Put, entry_checksum


def typed_field(forms: Forms, year: int, elster_id: str) -> FormField | None:
    """Das Eintippfeld `elster_id` im Katalog des Jahres, falls es eines ist."""
    return next((f for f in forms.get(year, ()) if f.elster_id == elster_id and f.typed), None)


def input_problem(forms: Forms, entry: FormInput) -> str | None:
    """Schreibweg: warum die Eingabe nicht zu ihrem Feld passt; `None`, wenn sie passt."""
    field = typed_field(forms, entry.year, entry.elster_id)
    if field is None or field.typed is None:
        return "Dieses Feld nimmt keine Eingabe."
    return field.typed.check(entry.content, entry.year)


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

    Leerer Text nimmt die Eingabe zurück; dann ist das Feld wieder noch nicht berechenbar. Ob der
    Text zum Feld passt, prüft der Schreibweg (`input_problem`).
    """
    if field.typed is None or field.elster_id is None:
        return [], "Dieses Feld nimmt keine Eingabe."
    text = text.strip()
    existing = current_input(state, year, field)
    if not text:
        return ([Delete(existing.address, entry_checksum(existing))] if existing else []), None
    if existing is None:
        entry = FormInput(owner=state.user, year=year, elster_id=field.elster_id, content=text)
        return [Put(entry)], None
    updated = existing.model_copy(update={"content": text})
    return [Put(updated, expected=entry_checksum(existing))], None
