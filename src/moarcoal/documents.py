"""Dokumentarten der Module und das Aufnehmen einer Datei vom Ablageort (docs/grundgeruest.md, 3.6).

Aufnehmen macht aus einer Datei ein Dokument und liest es, wenn die Dokumentart eine Einlese-Regel
hat, exakt ein; beides geschieht in einem Vorgang. Die Datei selbst bleibt am Ablageort.
"""

import datetime
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from moarcoal.extraction_template import ExtractionTemplate
from moarcoal.storage import (
    Applied,
    Document,
    Entry,
    Put,
    SiteFileError,
    State,
    Store,
)

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
    """

    key: str
    title: str
    has_period: bool
    read_in: Callable[[Document, bytes], Sequence[Entry]]
    extraction_template: ExtractionTemplate | None = None


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
) -> TakenIn | IntakeRejected:
    """Datei am Ablageort aufnehmen. `year` gilt als Bezugszeitraum, wenn die Art einen hat."""
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
    result = store.apply([Put(document), *(Put(entry) for entry in entries)])
    if not isinstance(result, Applied):
        return IntakeRejected(tuple(result.reasons.values()))
    return TakenIn(document, entries)


def _already_taken_in(state: State, user: str, sha256: str) -> bool:
    return any(d.owner == user and d.sha256 == sha256 for d in state.of_kind(Document))
