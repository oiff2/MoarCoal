"""Fachkern des Vertrags: lesen und die Änderungen fürs Anlegen und Zuordnen (Spec 3.2, #170).

Rein: Stand rein, Ergebnis oder Änderungen raus; geschrieben wird über `Store.apply`.
"""

import datetime

from moarcoal.issuer_field import IssuerChoice
from moarcoal.storage import (
    Agreement,
    Change,
    Document,
    EntryAddress,
    Put,
    State,
    entry_checksum,
    name_key,
)
from moarcoal.storage.agreements import CATEGORY_MAX, NAME_MAX, NUMBER_MAX


class AgreementInvalid(ValueError):
    """Eine Angabe zum Vertrag stimmt nicht; die Meldung (eine Zeile je Hinweis) ist für den
    Nutzer."""

    @property
    def problems(self) -> list[str]:
        return str(self).splitlines()


def agreements_of(state: State, user: str) -> list[Agreement]:
    """Die Verträge des Nutzers, nach Bezeichnung sortiert."""
    found = [a for a in state.of_kind(Agreement) if a.owner == user]
    return sorted(found, key=lambda a: (name_key(a.name), a.id))


def documents_of_agreement(state: State, agreement: Agreement) -> list[Document]:
    """Die Dokumente des Nutzers, die dem Vertrag zugeordnet sind, nach Pfad sortiert."""
    found = [
        d
        for d in state.of_kind(Document)
        if d.owner == agreement.owner and agreement.address in d.assignments
    ]
    return sorted(found, key=lambda d: (d.site, d.path, d.id))


def agreements_of_document(state: State, document: Document) -> list[Agreement]:
    """Die Verträge, denen das Dokument zugeordnet ist, nach Bezeichnung sortiert."""
    found = [state.get(address) for address in document.assignments]
    return sorted(
        (a for a in found if isinstance(a, Agreement)), key=lambda a: (name_key(a.name), a.id)
    )


def assign(document: Document, target: EntryAddress) -> Put:
    """Das Dokument dem Eintrag zuordnen; ist es ihm schon zugeordnet, bleibt es dabei."""
    if target in document.assignments:
        return Put(document, expected=entry_checksum(document))
    changed = document.model_copy(update={"assignments": (*document.assignments, target)})
    return Put(changed, expected=entry_checksum(document))


def unassign(document: Document, target: EntryAddress) -> Put:
    """Die Zuordnung des Dokuments zum Eintrag lösen."""
    kept = tuple(a for a in document.assignments if a != target)
    return Put(document.model_copy(update={"assignments": kept}), expected=entry_checksum(document))


def _date(text: str, label: str, problems: list[str]) -> datetime.date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        problems.append(f"{label}: Datum als JJJJ-MM-TT")
        return None


def agreement_changes(
    owner: str,
    entry_id: str,
    choice: IssuerChoice,
    fields: dict[str, str],
    expected: str | None = None,
) -> list[Change]:
    """Die Änderungen fürs Anlegen (`expected=None`) oder Ändern eines Vertrags aus den
    Formularfeldern; die des Vertragspartners (neuer Aussteller oder Alias, `choice`) gehören in
    denselben Vorgang. Wirft `AgreementInvalid` mit einem Hinweis je Feld."""
    problems: list[str] = []
    if choice.address is None:
        problems.append("Vertragspartner: einen Aussteller wählen oder neu eingeben")
    name = fields.get("name", "").strip()
    if not name or len(name) > NAME_MAX:
        problems.append(f"Bezeichnung: nicht leer, höchstens {NAME_MAX} Zeichen")
    number = fields.get("number", "").strip()
    if len(number) > NUMBER_MAX:
        problems.append(f"Vertragsnummer: höchstens {NUMBER_MAX} Zeichen")
    category = fields.get("category", "").strip()
    if len(category) > CATEGORY_MAX:
        problems.append(f"Art: höchstens {CATEGORY_MAX} Zeichen")
    start = _date(fields.get("start", ""), "Beginn", problems)
    end = _date(fields.get("end", ""), "Ende", problems)
    if start and end and end < start:
        problems.append("Ende: nicht vor dem Beginn")
    if problems or choice.address is None:
        raise AgreementInvalid("\n".join(problems))
    agreement = Agreement(
        id=entry_id,
        owner=owner,
        issuer=choice.address,
        name=name,
        number=number,
        category=category,
        start=start,
        end=end,
    )
    return [*choice.changes, Put(agreement, expected=expected)]
