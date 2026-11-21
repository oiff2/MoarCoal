"""Angaben zur Person und der eigene Aussteller des Nutzers (docs/grundgeruest.md, 3.2; ADR 0009).

Reiner Kern: Stand rein, Liste von Änderungen raus. Geschrieben wird über `Store.apply`.
"""

import datetime
import re
from dataclasses import dataclass

from moarcoal.storage import (
    COMMON_OWNER,
    Change,
    Entry,
    Issuer,
    PersonalDetails,
    Put,
    Religion,
    ReligionMembership,
    State,
    entry_checksum,
    issuer_with_name,
    name_key,
)
from moarcoal.storage.identifiers import (
    iban_problem,
    id_number_problem,
    normalize_iban,
    normalize_id_number,
)
from moarcoal.storage.personal_details import TEXT_MAX, religion_dates_problem


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


@dataclass(frozen=True)
class PersonForm:
    """Die übrigen Angaben zur Person, wie das Formular sie liefert (Texte, nichts geprüft).

    `religions` sind Paare (Datum, Gemeinschaft); ein Paar ohne beides zählt nicht.
    """

    birth_date: str = ""
    id_number: str = ""
    title: str = ""
    street: str = ""
    house_number: str = ""
    postal_code: str = ""
    city: str = ""
    iban: str = ""
    account_holder: str = ""
    religions: tuple[tuple[str, str], ...] = ()


_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def parse_date(text: str) -> datetime.date | None:
    """Ein Datum als JJJJ-MM-TT oder TT.MM.JJJJ; `None`, wenn es keines ist."""
    text = text.strip()
    try:
        if match := _DATE.fullmatch(text):
            day, month, year = (int(g) for g in match.groups())
            return datetime.date(year, month, day)
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def religion_on(details: PersonalDetails, day: datetime.date) -> Religion | None:
    """Die Religion am Tag `day`: die letzte Angabe bis dahin; `None`, wenn es keine gibt (nicht
    bekannt, nie „keine“)."""
    until = [m for m in details.religions if m.from_date <= day]
    return max(until, key=lambda m: m.from_date).religion if until else None


def church_tax_applies(details: PersonalDetails, year: int) -> bool | None:
    """Ob im Jahr Kirchensteuer anfällt: `True`, sobald der Nutzer im Jahr einer Gemeinschaft
    angehört, die sie erhebt; `False`, wenn er das ganze Jahr keiner angehört; `None`, wenn das
    Jahr nicht ganz belegt ist und keine bekannte Zeit eine erhebende Gemeinschaft zeigt."""
    at_start = religion_on(details, datetime.date(year, 1, 1))
    during = [
        m.religion
        for m in details.religions
        if datetime.date(year, 1, 1) < m.from_date <= datetime.date(year, 12, 31)
    ]
    if any(r.levies_church_tax for r in (*during, *([at_start] if at_start else []))):
        return True
    return None if at_start is None else False


def _text(value: str, label: str, problems: list[str]) -> str | None:
    value = value.strip()
    if len(value) > TEXT_MAX:
        problems.append(f"{label}: höchstens {TEXT_MAX} Zeichen")
    return value or None


def _memberships(
    rows: tuple[tuple[str, str], ...], problems: list[str]
) -> tuple[ReligionMembership, ...]:
    found: list[ReligionMembership] = []
    for date_text, religion_text in rows:
        if not date_text.strip() and not religion_text.strip():
            continue
        since = parse_date(date_text)
        try:
            religion = Religion(religion_text.strip())
        except ValueError:
            problems.append("Religion: Gemeinschaft aus der Liste wählen")
            continue
        if since is None:
            problems.append("Religion: ab wann (Datum TT.MM.JJJJ)")
        else:
            found.append(ReligionMembership(from_date=since, religion=religion))
    if problem := religion_dates_problem(tuple(found)):
        problems.append(problem)
    return tuple(sorted(found, key=lambda m: m.from_date))


def _more_fields(form: PersonForm, problems: list[str]) -> dict[str, object]:
    """Die geprüften Felder der Angaben aus dem Formular; Gründe gehen in `problems`."""
    birth = None
    if form.birth_date.strip() and (birth := parse_date(form.birth_date)) is None:
        problems.append("Geburtsdatum: Datum als TT.MM.JJJJ")
    id_number = _text(normalize_id_number(form.id_number), "Identifikationsnummer", problems)
    if id_number is not None and (problem := id_number_problem(id_number)):
        problems.append(problem)
    iban = _text(normalize_iban(form.iban), "IBAN", problems)
    if iban is not None and (problem := iban_problem(iban)):
        problems.append(problem)
    return {
        "birth_date": birth,
        "id_number": id_number,
        "iban": iban,
        "title": _text(form.title, "Titel", problems),
        "street": _text(form.street, "Straße", problems),
        "house_number": _text(form.house_number, "Hausnummer", problems),
        "postal_code": _text(form.postal_code, "Postleitzahl", problems),
        "city": _text(form.city, "Ort", problems),
        "account_holder": _text(form.account_holder, "Kontoinhaber", problems),
        "religions": _memberships(form.religions, problems),
    }


def personal_details_changes(
    state: State,
    user: str,
    first_name: str,
    last_name: str,
    expected: str = "",
    *,
    more: PersonForm | None = None,
) -> list[Change]:
    """Änderungen, die Angaben und eigenen Aussteller in einem Vorgang anlegen oder angleichen.

    `expected` ist die Prüfsumme der bekannten Fassung der Angaben (nur beim Ändern). `more` sind
    die übrigen Angaben aus dem Formular; ohne sie bleiben die vorhandenen unverändert. Wirft
    `PersonalDetailsInvalid` mit allen Gründen; die Prüfziffer und die Prüfsumme prüft zusätzlich
    der Vorgang (`check_personal_details`).
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
    fields = {} if more is None else _more_fields(more, problems)
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
                PersonalDetails(
                    owner=user,
                    first_name=first,
                    last_name=last,
                    issuer=issuer.address,
                    **fields,  # pyright: ignore[reportArgumentType]
                )
            )
        )
    else:
        changed = existing.model_copy(
            update={"first_name": first, "last_name": last, "issuer": issuer.address, **fields}
        )
        changes.append(Put(changed, expected))
    return changes


def own_issuer_first(issuers: list[Issuer], own: Issuer | None) -> list[Issuer]:
    """Die Liste mit dem eigenen Aussteller an erster Stelle, falls er in ihr vorkommt."""
    if own is None:
        return issuers
    return sorted(issuers, key=lambda i: i.id != own.id)  # stabil: Rest behält die Reihenfolge
