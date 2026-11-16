"""Dokumentarten, Aufnehmen und Einlesen einer Datei vom Ablageort (docs/grundgeruest.md, 3.6).

Aufnehmen macht aus einer Datei ein Dokument und liest es, wenn die Dokumentart eine Einlese-Regel
hat, exakt ein; beides geschieht in einem Vorgang. Die Datei selbst bleibt am Ablageort.

Beim Start liest `read_in_again` jedes Dokument neu ein, dessen eingelesene Einträge eine ältere
Fassung der Einlese-Regel tragen. Ein geänderter Wert ersetzt den alten; was sich geändert hat,
hält eine Neueinlesung fest, daraus wird der Hinweis-Befund „Einlesen hat einen Wert geändert“.
"""

import datetime
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR, year_of
from moarcoal.extraction_template import ExtractionTemplate
from moarcoal.issuer_field import IssuerChoice, resolve_issuer
from moarcoal.links import document_url
from moarcoal.storage import (
    Applied,
    Change,
    Delete,
    Document,
    Entry,
    EntryAddress,
    Put,
    ReadInDifference,
    ReadInEntry,
    Rereading,
    SiteFileError,
    State,
    Store,
    entry_checksum,
)
from moarcoal.storage.documents import (
    ALREADY_TAKEN_IN,
    TEXT_MAX,
    documents_of_file,
    exists_already,
    period_clash,
)
from moarcoal.values.findings import READ_IN_CHANGED, Finding, Severity

if TYPE_CHECKING:
    from moarcoal.values.engine import Values

DUPLICATE_DOCUMENT = "document_duplicate"
MAX_DIFFERENCES = 50  # so viele Stellen hält eine Neueinlesung fest; gezählt werden alle
SHOWN_DIFFERENCES = 3  # so viele nennt der Befund
OWN_FIELDS = frozenset({"id", "owner", "document", "reader_version"})  # kein eingelesener Wert
YEAR_NOT_A_NUMBER = "Steuerjahr: ganze Zahl, z. B. 2025"


class ReadInError(Exception):
    """Die Einlese-Regel kann die Datei nicht lesen; die Meldung ist für den Nutzer."""


class ReadInRuleBroken(Exception):
    """Eine Einlese-Regel hält ihren Vertrag nicht ein (Programmfehler)."""


@dataclass(frozen=True)
class DocumentKind:
    """Eine Dokumentart, wie die Modulanmeldung sie nennt.

    `read_in` ist die Einlese-Regel: eine reine Funktion aus Dokument und Dateiinhalt, die die
    Einträge des Moduls liefert (oder `ReadInError` wirft). Sie fasst keine Datei an. Jeder
    Eintrag nennt das Dokument, dessen Eigentümer und `reader_version`, die Fassung der Regel;
    wer die Regel so ändert, dass anderes herauskommen kann, zählt die Fassung hoch.
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
    read_in: Callable[[Document, bytes], Sequence[ReadInEntry]]
    reader_version: int
    extraction_template: ExtractionTemplate | None = None
    name_patterns: tuple[str, ...] = ()
    after_take_in: Callable[[Document, Sequence[Entry], "Values"], Sequence[Change]] | None = None
    unique_per_period: bool = False


@dataclass(frozen=True)
class TakenIn:
    document: Document
    entries: tuple[ReadInEntry, ...]


@dataclass(frozen=True)
class IntakeRejected:
    """`existing`: bei „Existiert bereits“ das vorhandene Dokument, auf das die Seite verweist."""

    reasons: tuple[str, ...]
    existing: Document | None = None


@dataclass(frozen=True)
class DocumentChoice:
    """Aussteller, Art und Jahr aus dem Formular eines Dokuments (Aufnehmen oder Ändern).

    `kind_key` ist leer für „Beleg“ und `None`, wenn das Formular keine Art schickt (gesperrt);
    `year` ist `DEFAULT_YEAR`, wenn die Art keinen Bezugszeitraum hat.
    """

    issuer: IssuerChoice
    kind_key: str | None
    year: int


def read_document_choice(
    state: State, kinds: Mapping[str, DocumentKind], fields: Mapping[str, str]
) -> DocumentChoice | IntakeRejected:
    """Liest Art, Jahr und Aussteller aus den Formularfeldern `kind`, `year` und denen des
    Aussteller-Felds; was sich nicht lesen lässt, weist es ab wie `take_in`."""
    kind_key = fields.get("kind")
    kind = kinds.get(kind_key or "")
    if kind_key and kind is None:
        return IntakeRejected(("Bitte eine Dokumentart wählen.",))
    year = DEFAULT_YEAR
    if kind is not None and kind.has_period:
        given = year_of(fields.get("year", ""))
        if given is None:
            return IntakeRejected((YEAR_NOT_A_NUMBER,))
        year = given
    issuer = resolve_issuer(state, fields)
    if isinstance(issuer, str):
        return IntakeRejected((issuer,))
    return DocumentChoice(issuer, kind_key, year)


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
                    href=document_url(d.id),
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
        content = store.sites.read(site, path)
    except SiteFileError as error:
        return IntakeRejected((str(error),))
    sha256 = hashlib.sha256(content).hexdigest()
    if documents_of_file(store.state().entries, user, sha256):  # Komfort: nicht erst einlesen
        return IntakeRejected((ALREADY_TAKEN_IN,))
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
        entries = _read_in(kind, document, content) if kind else ()
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
        if store.references_to(document.address, with_derived=True):
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
                content = store.sites.read(document.site, document.path)
                if hashlib.sha256(content).hexdigest() != document.sha256:
                    return IntakeRejected(("Die Datei hat sich seit dem Aufnehmen geändert.",))
                changes.extend(Put(entry) for entry in _read_in(kind, updated, content))
            except (SiteFileError, ReadInError) as error:
                return IntakeRejected((str(error),))
    changes.append(Put(updated, entry_checksum(document)))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _rejected(result.reasons, state, kinds, updated)
    return result


def _read_in(kind: DocumentKind, document: Document, content: bytes) -> tuple[ReadInEntry, ...]:
    """Die Einlese-Regel anwenden und ihren Vertrag prüfen."""
    entries = tuple(kind.read_in(document, content))
    for entry in entries:
        if not isinstance(entry, ReadInEntry):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ReadInRuleBroken(f"{kind.key}: {type(entry).__name__} ist kein ReadInEntry")
        if (entry.document, entry.owner, entry.reader_version) != (
            document.address,
            document.owner,
            kind.reader_version,
        ):
            raise ReadInRuleBroken(
                f"{kind.key}: {entry.address} nennt nicht Dokument, Eigentümer und Fassung"
            )
    return entries


# --- Neu einlesen beim Start ------------------------------------------------------------------


def read_entries_of(state: State, document: EntryAddress) -> list[ReadInEntry]:
    """Die eingelesenen Einträge eines Dokuments, nach Adresse sortiert."""
    found = [
        e for e in state.entries.values() if isinstance(e, ReadInEntry) and e.document == document
    ]
    return sorted(found, key=lambda e: str(e.address))


def read_in_again(
    store: Store, kinds: Mapping[str, DocumentKind], now: datetime.datetime | None = None
) -> list[str]:
    """Neu einlesen, wo sich die Fassung der Einlese-Regel geändert hat (Start, Schritt 5).

    Je Dokument ein eigener Vorgang. Ist die Datei nicht lesbar, ihr Inhalt geändert oder lehnt
    die Regel sie jetzt ab, bleibt das alte Ergebnis stehen. Liefert je betroffenem Dokument
    eine Zeile fürs Protokoll des Starts.
    """
    moment = now or datetime.datetime.now(datetime.UTC)
    report: list[str] = []
    for document in sorted(store.state().of_kind(Document), key=lambda d: str(d.address)):
        kind = kinds.get(document.document_kind or "")
        if kind is None:
            continue
        old = read_entries_of(store.state(), document.address)
        if not old or all(e.reader_version == kind.reader_version for e in old):
            continue  # nichts eingelesen oder schon mit der aktuellen Fassung
        name = f"{document.site}/{document.path}"
        try:
            content = store.sites.read(document.site, document.path)
        except SiteFileError as error:
            report.append(f"{name}: nicht neu eingelesen, {error}")
            continue
        if hashlib.sha256(content).hexdigest() != document.sha256:
            report.append(f"{name}: nicht neu eingelesen, der Inhalt der Datei hat sich geändert.")
            continue
        try:
            new = _read_in(kind, document, content)
        except ReadInError as error:
            report.append(f"{name}: nicht neu eingelesen, {error}")
            continue
        changes, differences = _replace(old, new)
        if differences:
            changes.append(
                Put(
                    Rereading(
                        owner=document.owner,
                        document=document.address,
                        reread_at=moment,
                        version_before=min(e.reader_version for e in old),
                        version_after=kind.reader_version,
                        differences=tuple(differences[:MAX_DIFFERENCES]),
                        difference_count=len(differences),
                    )
                )
            )
        result = store.apply(changes)
        if not isinstance(result, Applied):
            reasons = "; ".join(result.reasons.values())
            report.append(f"{name}: nicht neu eingelesen ({reasons})")
            continue
        report.append(f"{name}: neu eingelesen, {len(differences)} Stelle(n) geändert.")
    return report


def _replace(
    old: Sequence[ReadInEntry], new: Sequence[ReadInEntry]
) -> tuple[list[Change], list[ReadInDifference]]:
    """Änderungen, die das alte Ergebnis durch das neue ersetzen, und die geänderten Stellen.

    Hat eine Art vorher und nachher genau einen Eintrag, behält er seine Kennung und wird
    Feld für Feld verglichen; sonst werden die Einträge der Art als Ganzes ersetzt.
    """
    changes: list[Change] = []
    differences: list[ReadInDifference] = []
    kinds = dict.fromkeys(type(e).__name__ for e in (*old, *new))
    for kind in kinds:
        before = [e for e in old if type(e).__name__ == kind]
        after = [e for e in new if type(e).__name__ == kind]
        if len(before) == 1 and len(after) == 1:
            kept = after[0].model_copy(update={"id": before[0].id})
            changes.append(Put(kept, expected=entry_checksum(before[0])))
            differences.extend(_field_differences(kind, before[0], kept))
            continue
        changes.extend(Delete(e.address, entry_checksum(e)) for e in before)
        changes.extend(Put(e) for e in after)
        differences.extend(_entry_differences(kind, before, after))
    return changes, differences


def _flatten(value: object, location: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, inner in cast(dict[str, object], value).items():
            yield from _flatten(inner, f"{location}.{key}")
    elif isinstance(value, list):
        for number, inner in enumerate(cast(list[object], value), start=1):
            yield from _flatten(inner, f"{location}[{number}]")
    else:
        yield location, value if isinstance(value, str) else json.dumps(value)


def _values(kind: str, entry: ReadInEntry) -> dict[str, str]:
    dumped = entry.model_dump(mode="json", exclude=set(OWN_FIELDS))
    return dict(_flatten(dumped, kind))


def _clip(text: str | None) -> str | None:
    return None if text is None else text[:TEXT_MAX]


def _field_differences(
    kind: str, before: ReadInEntry, after: ReadInEntry
) -> list[ReadInDifference]:
    old, new = _values(kind, before), _values(kind, after)
    return [
        ReadInDifference(
            location=_clip(where) or kind, before=_clip(old.get(where)), after=_clip(new.get(where))
        )
        for where in dict.fromkeys((*old, *new))
        if old.get(where) != new.get(where)
    ]


def _entry_differences(
    kind: str, before: Sequence[ReadInEntry], after: Sequence[ReadInEntry]
) -> list[ReadInDifference]:
    """Einträge als Ganzes: was nur vorher bzw. nur nachher vorkommt."""

    def text(entry: ReadInEntry) -> str:
        return json.dumps(_values(kind, entry), ensure_ascii=False, sort_keys=True)

    old, new = Counter(map(text, before)), Counter(map(text, after))
    gone, added = old - new, new - old
    return [
        *(ReadInDifference(location=kind, before=_clip(t), after=None) for t in gone.elements()),
        *(ReadInDifference(location=kind, before=None, after=_clip(t)) for t in added.elements()),
    ]


# --- Befund „Einlesen hat einen Wert geändert“ ------------------------------------------------


def rereading_findings(
    state: State,
    user: str,
    year: int,
    kinds: Mapping[str, DocumentKind],
    entry_url: Callable[[EntryAddress], str | None],
) -> list[Finding]:
    """Ein Hinweis je Neueinlesung des Nutzers, deren Dokument das Jahr betrifft.

    Dokumente ohne Bezugszeitraum gelten für jedes Jahr. Der Link führt zum ersten
    eingelesenen Eintrag des Dokuments, wenn sein Modul eine Seite dafür hat.
    """
    found: list[Finding] = []
    for rereading in sorted(state.of_kind(Rereading), key=lambda r: (r.reread_at, r.id)):
        document = state.get(rereading.document)
        if rereading.owner != user or not isinstance(document, Document):
            continue
        start, end = document.period_start, document.period_end
        if start and end and not start.year <= year <= end.year:
            continue
        kind = kinds.get(document.document_kind or "")
        title = kind.title if kind else "Dokument"
        shown = "; ".join(_describe(d) for d in rereading.differences[:SHOWN_DIFFERENCES])
        more = rereading.difference_count - min(SHOWN_DIFFERENCES, len(rereading.differences))
        message = (
            f"{title} {document.path}: Neues Einlesen (Fassung {rereading.version_before} → "
            f"{rereading.version_after}) hat {rereading.difference_count} Stelle(n) geändert: "
            f"{shown}" + (f" und {more} weitere." if more > 0 else ".")
        )
        entries = read_entries_of(state, document.address)
        href = next((url for e in entries if (url := entry_url(e.address))), None)
        found.append(
            Finding(READ_IN_CHANGED, Severity.NOTE, rereading.address, message, href=href or "")
        )
    return found


def _describe(difference: ReadInDifference) -> str:
    def quoted(text: str | None) -> str:
        return "nicht vorhanden" if text is None else f"„{text}“"

    return f"{difference.location} {quoted(difference.before)} → {quoted(difference.after)}"
