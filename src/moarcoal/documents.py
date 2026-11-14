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
    entry_checksum,
)
from moarcoal.storage.documents import exists_already, period_clash
from moarcoal.storage.entries import referenced_addresses
from moarcoal.values.findings import Finding, Severity

if TYPE_CHECKING:
    from moarcoal.values.engine import Values

DUPLICATE_DOCUMENT = "document_duplicate"
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
    `name_patterns` sind optionale reguläre Ausdrücke (ohne Groß-/Kleinschreibung, gegen Datei- und
    Ordnernamen), mit denen das Aufnehmen-Formular die Art vorbelegt; ohne Muster nie.

    `after_take_in` ist die optionale Ergänzung beim Aufnehmen (Spec 3.6 Punkt 8): aus Dokument,
    eingelesenen Einträgen und `Values` auf einem vorläufigen Stand, der beide schon enthält,
    liefert sie Änderungen, die im selben Vorgang geschrieben werden. Sie kann das Aufnehmen nicht
    ablehnen; beim Neu-Einlesen läuft sie nicht erneut.

    `unique_per_period` (nur mit Bezugszeitraum): je Nutzer und Jahr höchstens ein Dokument dieser
    Art; der Schreibweg (`EntryKind.check` des Dokuments, `open_store(once_per_period=...)`) weist
    beim Aufnehmen und beim Ändern von Art oder Jahr ein zweites ab, vorhandene Dubletten bleiben
    und ergeben einen Hinweis.
    """

    key: str
    title: str
    has_period: bool
    read_in: Callable[[Document, bytes], Sequence[Entry]]
    extraction_template: ExtractionTemplate | None = None
    name_patterns: tuple[str, ...] = ()
    after_take_in: Callable[[Document, Sequence[Entry], "Values"], Sequence[Change]] | None = None
    unique_per_period: bool = False


@dataclass(frozen=True)
class TakenIn:
    document: Document
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class IntakeRejected:
    """`existing`: bei „Existiert bereits“ das vorhandene Dokument, auf das die Seite verweist."""

    reasons: tuple[str, ...]
    existing: Document | None = None


def _year_problem(year: int) -> str | None:
    if MIN_YEAR <= year <= MAX_YEAR:
        return None
    return f"Steuerjahr: Jahr zwischen {MIN_YEAR} und {MAX_YEAR}"


def _period(
    kind: DocumentKind | None, year: int
) -> tuple[datetime.date | None, datetime.date | None]:
    """Bezugszeitraum (Beginn, Ende) des Jahrs, wenn die Art einen hat."""
    if kind is None or not kind.has_period:
        return None, None
    return datetime.date(year, 1, 1), datetime.date(year, 12, 31)


def _rejected(
    reasons: Mapping[EntryAddress, str],
    state: State,
    kinds: Mapping[str, DocumentKind],
    document: Document,
) -> IntakeRejected:
    """Die Abweisung des Schreibwegs; bei „Existiert bereits“ mit dem vorhandenen Dokument."""
    kind = kinds.get(document.document_kind or "")
    existing = period_clash(state.entries, document, {kind.key} if kind else ())
    if (
        kind is not None
        and existing is not None
        and reasons.get(document.address) == exists_already(kind.title, existing)
    ):
        return IntakeRejected(tuple(reasons.values()), existing)
    return IntakeRejected(tuple(reasons.values()))


def duplicate_findings(state: State, user: str, kinds: Mapping[str, DocumentKind]) -> list[Finding]:
    """Hinweis je Dokument des Nutzers, das eine Dokumentart mit `unique_per_period` mit einem
    anderen im selben Jahr teilt (vorhandene Dubletten bleiben bestehen)."""
    found: list[Finding] = []
    for d in sorted(state.of_kind(Document), key=lambda d: str(d.address)):
        kind = kinds.get(d.document_kind or "")
        if (
            d.owner == user
            and kind is not None
            and period_clash(state.entries, d, {kind.key}) is not None
        ):
            year = d.period_start.year if d.period_start else ""
            found.append(
                Finding(
                    DUPLICATE_DOCUMENT,
                    Severity.NOTE,
                    d.address,
                    f"Existiert mehrfach: {kind.title} {year}: {d.path}",
                    href=d.url,
                )
            )
    return found


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
    Eine leere `kind_key` nimmt ein Dokument ohne Dokumentart auf (Beleg, ohne Bezugszeitraum).

    `values_on` bildet `Values` auf einem Stand; die Ergänzung der Dokumentart braucht es.
    `issuer` ist der freiwillige Aussteller; `issuer_changes` (neuer Aussteller, neuer Alias)
    werden im selben Vorgang geschrieben, bei Abweisung bleibt nichts davon stehen.
    """
    kind = kinds[kind_key] if kind_key else None  # leer = Beleg; unbekannte Art: Programmfehler
    if (problem := _year_problem(year)) is not None:
        return IntakeRejected((problem,))
    try:
        content = store.read_site_file(site, path)
    except SiteFileError as error:
        return IntakeRejected((str(error),))
    sha256 = hashlib.sha256(content).hexdigest()
    if _already_taken_in(store.state(), user, sha256):
        return IntakeRejected(("Diese Datei ist schon aufgenommen.",))
    start, end = _period(kind, year)
    try:
        document = Document(
            owner=user,
            site=site,
            path=path,
            sha256=sha256,
            document_kind=kind.key if kind else None,
            issuer=issuer,
            period_start=start,
            period_end=end,
            taken_in_at=datetime.datetime.now(datetime.UTC),
        )
    except ValidationError:
        return IntakeRejected(("Ablageort und Pfad müssen angegeben werden.",))
    try:
        entries = tuple(kind.read_in(document, content)) if kind else ()
    except ReadInError as error:
        return IntakeRejected((str(error),))
    taken = [document, *entries]
    changes: list[Change] = [*issuer_changes, *(Put(entry) for entry in taken)]
    if kind is not None and kind.after_take_in is not None:
        if values_on is None:
            raise ValueError(f"{kind.key}: die Ergänzung beim Aufnehmen braucht `values_on`")
        provisional = State({**store.state().entries, **{e.address: e for e in taken}})
        changes.extend(kind.after_take_in(document, entries, values_on(provisional)))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _rejected(result.reasons, store.state(), kinds, document)
    return TakenIn(document, entries)


def _already_taken_in(state: State, user: str, sha256: str) -> bool:
    return any(d.owner == user and d.sha256 == sha256 for d in state.of_kind(Document))


def references_to(state: State, document: Document) -> list[Entry]:
    """Die Einträge, die auf das Dokument verweisen (Einlesung, Vorschlag, Schnappschuss, …);
    solange es welche gibt, hängt etwas daran: Art und Jahr sind gesperrt, Löschen weist ab."""
    found = [
        e
        for e in state.entries.values()
        if e.address != document.address and document.address in referenced_addresses(e)
    ]
    return sorted(found, key=lambda e: str(e.address))


def change_document(
    store: Store,
    kinds: Mapping[str, DocumentKind],
    document: Document,
    issuer: EntryAddress | None,
    issuer_changes: Sequence[Change] = (),
    kind_key: str | None = None,
    year: int | None = None,
) -> Applied | IntakeRejected:
    """Ändert das Dokument: der Aussteller immer, Art und Jahr nur, solange nichts daran hängt.

    `kind_key` (leer = Beleg) und `year` sind nur beim Ändern von Art oder Jahr angegeben;
    hängt etwas am Dokument, sind sie ein Fehler. Wechselt die Art, wird das Dokument nach ihrer
    Einlese-Regel neu eingelesen (die Ergänzung beim Aufnehmen läuft nicht).
    """
    state = store.state()
    updated = document.model_copy(update={"issuer": issuer})
    changes: list[Change] = [*issuer_changes]
    if kind_key is not None:
        if references_to(state, document):
            return IntakeRejected(("An dem Dokument hängt etwas; Art und Jahr sind gesperrt.",))
        kind = kinds.get(kind_key)
        if kind_key and kind is None:
            return IntakeRejected(("Bitte eine Dokumentart wählen.",))
        if year is not None and (problem := _year_problem(year)) is not None:
            return IntakeRejected((problem,))
        start, end = _period(kind, year or MIN_YEAR)
        updated = updated.model_copy(
            update={"document_kind": kind_key or None, "period_start": start, "period_end": end}
        )
        if kind is not None and kind_key != document.document_kind:
            try:
                content = store.read_site_file(document.site, document.path)
                if hashlib.sha256(content).hexdigest() != document.sha256:
                    return IntakeRejected(("Die Datei hat sich seit dem Aufnehmen geändert.",))
                changes.extend(Put(entry) for entry in kind.read_in(updated, content))
            except (SiteFileError, ReadInError) as error:
                return IntakeRejected((str(error),))
    changes.append(Put(updated, entry_checksum(document)))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _rejected(result.reasons, state, kinds, updated)
    return result
