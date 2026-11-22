"""Eingaben zur Person im Steuerjahr: aus dem Formular eine Liste von Änderungen machen."""

from collections.abc import Iterable

from moarcoal.modules.tax_year.anlage_est1a import IN_THIS_RETURN
from moarcoal.modules.tax_year.anlagen import Anlage, field_catalog
from moarcoal.modules.tax_year.entries import YearPersonInput, current_person_input
from moarcoal.modules.tax_year.fields import FormField, TextSource
from moarcoal.registration import ModuleState
from moarcoal.storage import Change, Delete, Put, entry_checksum


def year_person_input_changes(
    state: ModuleState, year: int, occupation: str, phone: str, in_this_return: str, note: str
) -> list[Change]:
    """Die Änderungen, die die Eingaben zur Person im Jahr ablegen.

    Leere Texte sind noch nicht angegeben; sind alle leer, wird die Eingabe zurückgenommen. Ob
    das Telefon eine Nummer ist und die Notiz nicht zu lang, prüft der Schreibweg. In der Notiz
    bleiben Zeilenumbrüche (als `\\n`) erhalten; Ränder werden entfernt.
    """
    texts = {
        "occupation": occupation.strip() or None,
        "phone": phone.strip() or None,
        "in_this_return": in_this_return.strip() or None,
        "note": note.replace("\r\n", "\n").replace("\r", "\n").strip() or None,
    }
    existing = current_person_input(state, year)
    if not any(texts.values()):
        return [Delete(existing.address, entry_checksum(existing))] if existing else []
    if existing is None:
        return [Put(YearPersonInput(owner=state.user, year=year).model_copy(update=texts))]
    return [Put(existing.model_copy(update=texts), expected=entry_checksum(existing))]


def field_texts(state: ModuleState, fields: Iterable[FormField], year: int) -> dict[str, str]:
    """Der Inhalt der Felder mit Text im Jahr, je E-Kennung: aus den Angaben zur Person des
    Nutzers und seiner Eingabe zur Person im Jahr. Was fehlt, ist nicht dabei (noch nicht
    berechenbar), nie ein leerer Text."""
    details = state.personal_details()
    entry = current_person_input(state, year)
    found: dict[str, str] = {}
    for field in fields:
        if not isinstance(field.kind, TextSource):
            continue
        if text := field.kind.read(details, entry, year):
            found[field.elster_id] = text
    return found


def field_reasons(state: ModuleState, fields: Iterable[FormField], year: int) -> dict[str, str]:
    """Je E-Kennung der Grund, warum ein Feld mit Text trotz Angaben nicht berechenbar ist."""
    details = state.personal_details()
    entry = current_person_input(state, year)
    found: dict[str, str] = {}
    for field in fields:
        if not isinstance(field.kind, TextSource) or field.kind.why_not is None:
            continue
        if reason := field.kind.why_not(details, entry, year):
            found[field.elster_id] = reason
    return found


def in_this_return_choices(anlagen: Iterable[Anlage], year: int) -> tuple[str, ...]:
    """Die Optionen der Auswahl „In dieser Steuererklärung“ im Jahr (aus der Struktur); leer, wenn
    das Jahr keinen Katalog hat und jeder Text gilt."""
    kind = next(
        (f.kind for f in field_catalog(anlagen, year) if f.elster_id == IN_THIS_RETURN), None
    )
    return kind.choices if isinstance(kind, TextSource) else ()


def person_input_problem(anlagen: Iterable[Anlage], entry: YearPersonInput) -> str | None:
    """Schreibweg: die Auswahl „In dieser Steuererklärung“ ist eine der Optionen des Jahrs."""
    choices = in_this_return_choices(anlagen, entry.year)
    if entry.in_this_return is not None and choices and entry.in_this_return not in choices:
        return "In dieser Steuererklärung: Wähle eine der Möglichkeiten."
    return None
