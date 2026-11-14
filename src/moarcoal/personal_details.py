"""Angaben zur Person und der eigene Aussteller des Nutzers (docs/grundgeruest.md, 3.2; ADR 0009).

Reiner Kern: Stand rein, Liste von Änderungen raus. Geschrieben wird über `Store.apply`.
"""

from moarcoal.storage import (
    COMMON_OWNER,
    Change,
    Entry,
    Issuer,
    PersonalDetails,
    Put,
    State,
    entry_checksum,
    issuer_with_name,
    name_key,
)


class PersonalDetailsInvalid(ValueError):
    """Die Eingabe ist unvollständig; die Texte sind für den Nutzer."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


def details_of(state: State, user: str) -> PersonalDetails | None:
    """Die Angaben zur Person des Nutzers; ohne sie gibt es den Nutzer nicht."""
    return next((d for d in state.of_kind(PersonalDetails) if d.owner == user), None)


def own_issuer(state: State, details: PersonalDetails) -> Issuer | None:
    """Der eigene Aussteller; die Adresse wird über zusammengeführte Kennungen aufgelöst."""
    found = None if details.issuer is None else state.resolve(details.issuer)
    return found if isinstance(found, Issuer) else None


def details_for_issuer(state: State, issuer: Issuer) -> PersonalDetails | None:
    """Die Angaben, aus denen der Aussteller kommt (von irgendeinem Nutzer), sonst `None`."""
    for details in state.of_kind(PersonalDetails):
        own = own_issuer(state, details)
        if own is not None and own.id == issuer.id:
            return details
    return None


def _synced_issuer(state: State, details: PersonalDetails | None, name: str) -> Issuer:
    """Der Aussteller des Nutzers nach dem Speichern: Name `name`, Privatperson; der alte Name
    wird Alias. Fehlt der Aussteller, wird der im Katalog gleichnamige übernommen oder ein neuer
    angelegt."""
    current = None if details is None else own_issuer(state, details)
    if current is None:
        current = issuer_with_name(state.of_kind(Issuer), name)
    if current is None:
        return Issuer(owner=COMMON_OWNER, name=name, private_person=True)
    aliases = [a for a in current.aliases if name_key(a) != name_key(name)]
    if name_key(current.name) != name_key(name) and current.name not in aliases:
        aliases.append(current.name)
    return current.model_copy(
        update={"name": name, "aliases": tuple(aliases), "private_person": True}
    )


def personal_details_changes(
    state: State, user: str, first_name: str, last_name: str, expected: str = ""
) -> list[Change]:
    """Änderungen, die Angaben und eigenen Aussteller in einem Vorgang anlegen oder angleichen.

    `expected` ist die Prüfsumme der bekannten Fassung der Angaben (nur beim Ändern).
    Wirft `PersonalDetailsInvalid`, wenn Vorname oder Name fehlt.
    """
    first, last = first_name.strip(), last_name.strip()
    problems = [
        message
        for message, value in (
            ("Vorname: darf nicht leer sein", first),
            ("Name: darf nicht leer sein", last),
        )
        if not value
    ]
    if problems:
        raise PersonalDetailsInvalid(problems)
    existing = details_of(state, user)
    issuer = _synced_issuer(state, existing, f"{first} {last}")
    known: Entry | None = state.get(issuer.address)
    changes: list[Change] = []
    if issuer != known:
        changes.append(Put(issuer, None if known is None else entry_checksum(known)))
    if existing is None:
        changes.append(
            Put(
                PersonalDetails(owner=user, first_name=first, last_name=last, issuer=issuer.address)
            )
        )
    else:
        changed = existing.model_copy(
            update={"first_name": first, "last_name": last, "issuer": issuer.address}
        )
        changes.append(Put(changed, expected))
    return changes
