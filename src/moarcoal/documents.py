"""Dokumentarten der Module und das Aufnehmen einer Datei vom Ablageort (docs/grundgeruest.md, 3.6).

Aufnehmen macht aus einer Datei ein Dokument und liest es, wenn die Dokumentart eine Einlese-Regel
hat, exakt ein; beides geschieht in einem Vorgang. Die Datei selbst bleibt am Ablageort.
"""

import datetime
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from moarcoal.extraction_template import ExtractionTemplate
from moarcoal.storage import (
    Applied,
    Change,
    Document,
    Entry,
    EntryAddress,
    Put,
    SiteFileError,
    State,
    Store,
)

if TYPE_CHECKING:
    from moarcoal.values.engine import Values

MIN_YEAR = 2000
MAX_YEAR = 2100


class ReadInError(Exception):
    """Die Einlese-Regel kann die Datei nicht lesen; die Meldung ist für den Nutzer."""


@dataclass(frozen=True)
class DocumentKind:
    """Eine Dokumentart, wie die Modulanmeldung sie nennt.

    `read_in` ist die Einlese-Regel: eine reine Funktion aus Dokument und Dateiinhalt, die die
    Einträge des Moduls liefert (oder `ReadInError` wirft). Sie fasst keine Datei an.
    `extraction_template` ist die Auslese-Vorlage; ohne sie lässt sich die Art nicht auslesen.

    `after_take_in` ist die optionale Ergänzung beim Aufnehmen (Spec 3.6 Punkt 8): aus Dokument,
    eingelesenen Einträgen und `Values` auf einem vorläufigen Stand, der beide schon enthält,
    liefert sie Änderungen, die im selben Vorgang geschrieben werden. Sie kann das Aufnehmen nicht
    ablehnen; beim Neu-Einlesen läuft sie nicht erneut.
    """

    key: str
    title: str
    has_period: bool
    read_in: Callable[[Document, bytes], Sequence[Entry]]
    extraction_template: ExtractionTemplate | None = None
    after_take_in: Callable[[Document, Sequence[Entry], "Values"], Sequence[Change]] | None = None


@dataclass(frozen=True)
class TakenIn:
    document: Document
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class IntakeRejected:
    reasons: tuple[str, ...]


def take_in(
    store: Store,
    kinds: Mapping[str, DocumentKind],
    user: str,
    site: str,
    path: str,
    kind_key: str,
    year: int,
    *,
    values_on: Callable[[State], "Values"] | None = None,
    issuer: EntryAddress | None = None,
    issuer_changes: Sequence[Change] = (),
) -> TakenIn | IntakeRejected:
    """Datei am Ablageort aufnehmen. `year` gilt als Bezugszeitraum, wenn die Art einen hat.

    `values_on` bildet `Values` auf einem Stand; die Ergänzung der Dokumentart braucht es.
    `issuer` ist der freiwillige Aussteller; `issuer_changes` (neuer Aussteller, neuer Alias)
    werden im selben Vorgang geschrieben, bei Abweisung bleibt nichts davon stehen.
    """
    kind = kinds[kind_key]  # unbekannte Art ist ein Programmfehler
    if not MIN_YEAR <= year <= MAX_YEAR:
        return IntakeRejected((f"Steuerjahr: Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",))
    try:
        content = store.read_site_file(site, path)
    except SiteFileError as error:
        return IntakeRejected((str(error),))
    sha256 = hashlib.sha256(content).hexdigest()
    if _already_taken_in(store.state(), user, sha256):
        return IntakeRejected(("Diese Datei ist schon aufgenommen.",))
    try:
        document = Document(
            owner=user,
            site=site,
            path=path,
            sha256=sha256,
            document_kind=kind.key,
            issuer=issuer,
            period_start=datetime.date(year, 1, 1) if kind.has_period else None,
            period_end=datetime.date(year, 12, 31) if kind.has_period else None,
            taken_in_at=datetime.datetime.now(datetime.UTC),
        )
    except ValidationError:
        return IntakeRejected(("Ablageort und Pfad müssen angegeben werden.",))
    try:
        entries = tuple(kind.read_in(document, content))
    except ReadInError as error:
        return IntakeRejected((str(error),))
    taken = [document, *entries]
    changes: list[Change] = [*issuer_changes, *(Put(entry) for entry in taken)]
    if kind.after_take_in is not None:
        if values_on is None:
            raise ValueError(f"{kind.key}: die Ergänzung beim Aufnehmen braucht `values_on`")
        provisional = State({**store.state().entries, **{e.address: e for e in taken}})
        changes.extend(kind.after_take_in(document, entries, values_on(provisional)))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return IntakeRejected(tuple(result.reasons.values()))
    return TakenIn(document, entries)


def _already_taken_in(state: State, user: str, sha256: str) -> bool:
    return any(d.owner == user and d.sha256 == sha256 for d in state.of_kind(Document))
