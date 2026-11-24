"""Fachkern der Steuerlichen Bedeutung: welche Verträge in einem Jahr laufen und die Änderungen
fürs Setzen, Ändern und Entfernen. Rein: Stand rein, Ergebnis oder Änderungen raus; geschrieben
wird über `Store.apply` (Anbindung in `pages.py`)."""

import datetime
from collections.abc import Sequence

from moarcoal.modules.provision.entries import AgreementMeaning, TaxMeaning
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, Change, Delete, Put


class MeaningInvalid(ValueError):
    """Die gewählte Bedeutung gibt es nicht; die Meldung ist für den Nutzer."""


def runs_in(agreement: Agreement, year: int) -> bool:
    """Ob die Laufzeit des Vertrags das Jahr berührt; ohne Beginn oder Ende ist sie dort offen."""
    return (agreement.start is None or agreement.start <= datetime.date(year, 12, 31)) and (
        agreement.end is None or agreement.end >= datetime.date(year, 1, 1)
    )


def running_agreements(agreements: Sequence[Agreement], year: int) -> list[Agreement]:
    """Die Verträge, die im Jahr laufen, in der Reihenfolge von `agreements`."""
    return [a for a in agreements if runs_in(a, year)]


def meaning_of(state: ModuleState, agreement: Agreement) -> AgreementMeaning | None:
    """Der Eintrag mit der Steuerlichen Bedeutung des Vertrags, falls er eine hat."""
    return next((m for m in state.all(AgreementMeaning) if m.agreement == agreement.address), None)


def parse_meaning(text: str) -> TaxMeaning | None:
    """Die Wahl aus dem Formular: leer heißt keine Bedeutung, sonst eine der `TaxMeaning`."""
    text = text.strip()
    if not text:
        return None
    try:
        return TaxMeaning(text)
    except ValueError as error:
        raise MeaningInvalid("Bedeutung: eine der angebotenen wählen") from error


def meaning_changes(
    state: ModuleState, agreement: Agreement, meaning: TaxMeaning | None, seen: str
) -> list[Change]:
    """Die Änderung, mit der der Vertrag die Bedeutung `meaning` (`None`: keine) bekommt.

    `seen` ist die Prüfsumme des Eintrags, den der Nutzer vor sich hatte, leer wenn er keinen sah;
    `apply` weist ab, wenn der Eintrag inzwischen anders ist.
    """
    existing = meaning_of(state, agreement)
    if meaning is None:
        return [] if existing is None else [Delete(existing.address, expected=seen)]
    if existing is None:
        entry = AgreementMeaning(
            owner=agreement.owner, agreement=agreement.address, meaning=meaning
        )
        return [Put(entry, expected=seen or None)]
    return [Put(existing.model_copy(update={"meaning": meaning}), expected=seen)]
