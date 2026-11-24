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
from types import EllipsisType
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR, year_of
from moarcoal.extraction_template import ExtractionTemplate
from moarcoal.issuer_field import IssuerChoice, resolve_issuer
from moarcoal.storage import (
    Applied,
    Change,
    Delete,
    Document,
    Entry,
    EntryAddress,
    EntryKind,
    Issuer,
    Put,
    ReadInDifference,
    ReadInEntry,
    Rereading,
    SiteFile,
    SiteFileError,
    Sites,
    State,
    Store,
    entry_checksum,
)
from moarcoal.storage.documents import (
    ALREADY_TAKEN_IN,
    TEXT_MAX,
    UniqueKey,
    documents_of_file,
    exists_already,
    period_clash,
)
from moarcoal.storage.entries import falls_with, referenced_addresses, strong_references
from moarcoal.values.findings import READ_IN_CHANGED, Finding, Severity

if TYPE_CHECKING:
    from moarcoal.values.engine import Values

DUPLICATE_DOCUMENT = "document_duplicate"
UNREFERENCED_DOCUMENT = "document_unreferenced"  # Befundart: kein Eintrag verweist auf den Beleg
MAX_DIFFERENCES = 50  # so viele Stellen hält eine Neueinlesung fest; gezählt werden alle
SHOWN_DIFFERENCES = 3  # so viele nennt der Befund
SENSITIVE_SHOWN = "(sensibler Wert, nicht festgehalten)"
OWN_FIELDS = frozenset({"id", "owner", "document", "reader_version"})  # kein eingelesener Wert
YEAR_NOT_A_NUMBER = "Steuerjahr: ganze Zahl, z. B. 2025"
CHANGED_SINCE_SHOWN = "Die Datei hat sich seit der Anzeige geändert."
NO_FILES = "Es gibt keine Datei zum Aufnehmen."


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
    `unique_by` (nur mit `unique_per_period`): macht die Eindeutigkeit enger, sie gilt dann je
    Schlüssel und Jahr; Dokumente mit verschiedenem Schlüssel schließen sich nicht aus. Der
    Schlüssel kommt aus Dokument und Stand (`UniqueKey`; `unique_by_issuer` für „je Aussteller“),
    der Schreibweg ruft ihn nach dem Vorgang auf, sodass er die eingelesenen Einträge des
    Dokuments sieht. Die Abweisung nennt nie den Schlüssel selbst („Existiert bereits: Art Jahr“).
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
    unique_by: UniqueKey | None = None


def kind_title(kinds: Mapping[str, DocumentKind], key: str | None) -> str:
    """Titel der Dokumentart `key`; eine unbekannte Art zeigt ihren Schlüssel, ohne Art leer."""
    kind = kinds.get(key or "")
    return kind.title if kind else (key or "")


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
    """Aussteller, Art, Jahr und Bezeichnung aus dem Formular eines Dokuments (Aufnehmen oder
    Ändern).

    `kind_key` ist leer für „Beleg“ und `None`, wenn das Formular keine Art schickt (gesperrt);
    `year` ist `DEFAULT_YEAR`, wenn die Art keinen Bezugszeitraum hat.
    """

    issuer: IssuerChoice
    kind_key: str | None
    year: int
    label: str | None = None


def read_document_choice(
    state: State, kinds: Mapping[str, DocumentKind], fields: Mapping[str, str]
) -> DocumentChoice | IntakeRejected:
    """Liest Art, Jahr, Bezeichnung und Aussteller aus den Formularfeldern `kind`, `year`,
    `label` (leer: keine) und denen des Aussteller-Felds; was sich nicht lesen lässt, weist es
    ab wie `take_in`."""
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
    label = fields.get("label", "").strip() or None
    if label is not None and len(label) > TEXT_MAX:
        return IntakeRejected((f"Die Bezeichnung ist länger als {TEXT_MAX} Zeichen.",))
    issuer = resolve_issuer(state, fields)
    if isinstance(issuer, str):
        return IntakeRejected((issuer,))
    return DocumentChoice(issuer, kind_key, year, label)


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


def _clash(
    entries: Mapping[EntryAddress, Entry], document: Document, kind: DocumentKind | None
) -> Document | None:
    """Das Dokument, mit dem `document` die Eindeutigkeit seiner Dokumentart verletzt."""
    if kind is None:
        return None
    unique_by = {kind.key: kind.unique_by} if kind.unique_by else {}
    return period_clash(entries, document, {kind.key}, unique_by)


def _rejected(
    reasons: Mapping[EntryAddress, str],
    state: State,
    kinds: Mapping[str, DocumentKind],
    document: Document,
    attempted: Sequence[Change],
) -> IntakeRejected:
    """Die Abweisung des Schreibwegs; bei „Existiert bereits“ mit dem vorhandenen Dokument. Die
    Eindeutigkeit gilt auf dem Stand nach dem Vorgang (`attempted`), denn ihr Schlüssel kann in
    den neu eingelesenen Einträgen des Dokuments stehen."""
    kind = kinds.get(document.document_kind or "")
    after = {**state.entries, **{c.entry.address: c.entry for c in attempted if isinstance(c, Put)}}
    existing = _clash(after, document, kind)
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
        if d.owner == user and kind is not None and _clash(state.entries, d, kind) is not None:
            year = d.period_start.year if d.period_start else ""
            found.append(
                Finding(
                    DUPLICATE_DOCUMENT,
                    Severity.NOTE,
                    d.address,
                    f"Existiert mehrfach: {kind.title} {year}: {d.path}",
                )
            )
    return found


def unreferenced_document_findings(
    state: State,
    user: str,
    year: int,
    kinds: Mapping[str, DocumentKind],
    sites: Sites,
    entry_kinds: Mapping[str, EntryKind],
) -> list[Finding]:
    """Hinweis je Dokument von `user`, das zu `year` gehört (`belongs_to_year`), ohne Dokumentart
    mit Einlese-Regel ist und auf das kein Eintrag verweist (wie `Store.references_to`: schwache
    Verweise und Einträge, die mit ihm wegfallen, zählen nicht)."""
    found: list[Finding] = []
    for d in sorted(state.of_kind(Document), key=lambda d: str(d.address)):
        if d.owner != user or (d.document_kind or "") in kinds:
            continue
        if not belongs_to_year(d, year, state, sites):
            continue
        refs = strong_references(state.entries.values(), d.address, entry_kinds)
        if any(not falls_with(e, d.address, entry_kinds) for e in refs):
            continue
        found.append(
            Finding(
                UNREFERENCED_DOCUMENT,
                Severity.NOTE,
                d.address,
                f"Auf diesen Beleg verweist kein Eintrag: {document_name(d, state)}",
            )
        )
    return found


@dataclass(frozen=True)
class DocumentYears:
    """Die Jahre eines Dokuments: `years` sind die bestimmten; `every` heißt „jedes Jahr“ (offene
    Aufgabe, siehe `years_of_document`)."""

    years: frozenset[int] = frozenset()
    every: bool = False

    def __contains__(self, year: object) -> bool:
        return self.every or year in self.years

    def __bool__(self) -> bool:
        return self.every or bool(self.years)


def years_of_document(document: Document, state: State, sites: Sites) -> DocumentYears:
    """Die Jahre, zu denen das Dokument gehört (CONTEXT.md, Dokument): die sein Bezugszeitraum
    berührt; ohne Bezugszeitraum das Jahr seines Jahresordners; an einem Ablageort ohne Jahr die
    Jahre der Einträge mit Zeitbezug (Feld `year`), die auf es verweisen, und solange kein solcher
    Eintrag auf es verweist, jedes Jahr (offene Aufgabe). Die Regel gibt es nur hier;
    `belongs_to_year` fragt sie für ein Jahr ab."""
    if document.period_start is not None:
        if document.period_end is None:
            return DocumentYears()
        return DocumentYears(
            frozenset(range(document.period_start.year, document.period_end.year + 1))
        )
    site_year = sites.year_of(document.site)
    if site_year is not None:
        return DocumentYears(frozenset({site_year}))
    referring = frozenset(
        year
        for entry in state.entries.values()
        if isinstance(year := getattr(entry, "year", None), int)
        and document.address in referenced_addresses(entry)
    )
    return DocumentYears(referring, every=not referring)


def belongs_to_year(document: Document, year: int, state: State, sites: Sites) -> bool:
    """Ob das Dokument zu dem Jahr gehört (`years_of_document`)."""
    return year in years_of_document(document, state, sites)


def document_name(document: Document, state: State) -> str:
    """Anzeigename eines Dokuments: „Aussteller · Bezeichnung“; ohne Bezeichnung der Dateiname,
    ohne Aussteller nur die Bezeichnung."""
    if document.label is None:
        return document.path.rsplit("/", 1)[-1]
    issuer = state.get(document.issuer) if document.issuer else None
    if isinstance(issuer, Issuer):
        return f"{issuer.name} · {document.label}"
    return document.label


def _intake(
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
    label: str | None = None,
    expected_sha256: str | None = None,
) -> tuple[Document, tuple[ReadInEntry, ...], list[Change]] | IntakeRejected:
    """Die Änderungen, die das Aufnehmen der Datei braucht (Dokument, Einträge, Ergänzung, ohne
    sie zu schreiben); der eine Kern von `take_in` und `take_in_all`. `expected_sha256`: ist der
    Inhalt der Datei ein anderer, wird sie abgewiesen."""
    kind = kinds[kind_key] if kind_key else None  # leer = Beleg; unbekannte Art: Programmfehler
    if (problem := _year_problem(year)) is not None:
        return IntakeRejected((problem,))
    try:
        content = store.sites.read(site, path)
    except SiteFileError as error:
        return IntakeRejected((str(error),))
    sha256 = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and sha256 != expected_sha256:
        return IntakeRejected((CHANGED_SINCE_SHOWN,))
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
            label=label,
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
    if kind is not None:
        changes.extend(_after_take_in(kind, store, document, entries, values_on, taken))
    return document, entries, changes


def _after_take_in(
    kind: DocumentKind,
    store: Store,
    document: Document,
    entries: Sequence[Entry],
    values_on: Callable[[State], "Values"] | None,
    replacing: Sequence[Entry],
) -> Sequence[Change]:
    """Die Ergänzung der Dokumentart, wenn sie eine hat; `replacing` (Dokument und Einträge) gilt
    auf dem vorläufigen Stand, auf dem `values_on` rechnet. Die eine Regel für Aufnehmen mit Art
    und für das spätere Setzen der Art."""
    if kind.after_take_in is None:
        return []
    if values_on is None:
        raise ValueError(f"{kind.key}: die Ergänzung beim Aufnehmen braucht `values_on`")
    provisional = State({**store.state().entries, **{e.address: e for e in replacing}})
    return kind.after_take_in(document, entries, values_on(provisional))


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
    label: str | None = None,
) -> TakenIn | IntakeRejected:
    """Datei am Ablageort aufnehmen. `year` gilt als Bezugszeitraum, wenn die Art einen hat.
    Eine leere `kind_key` nimmt ein Dokument ohne Dokumentart auf (Beleg, ohne Bezugszeitraum).

    `values_on` bildet `Values` auf einem Stand; die Ergänzung der Dokumentart braucht es.
    `issuer` ist der freiwillige Aussteller, `label` die freiwillige Bezeichnung;
    `issuer_changes` (neuer Aussteller, neuer Alias) werden im selben Vorgang geschrieben, bei
    Abweisung bleibt nichts davon stehen.
    """
    prepared = _intake(
        store,
        kinds,
        user,
        site,
        path,
        kind_key,
        year,
        values_on=values_on,
        issuer=issuer,
        issuer_changes=issuer_changes,
        label=label,
    )
    if isinstance(prepared, IntakeRejected):
        return prepared
    document, entries, changes = prepared
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _rejected(result.reasons, store.state(), kinds, document, changes)
    return TakenIn(document, entries)


@dataclass(frozen=True)
class TakenInAll:
    """`taken`: die neuen Belege; `skipped`: je übersprungene Datei (mit Grund)."""

    taken: tuple[Document, ...]
    skipped: tuple[tuple[SiteFile, str], ...]


def take_in_all(store: Store, user: str, files: Sequence[SiteFile]) -> TakenInAll | IntakeRejected:
    """Nimmt alle Dateien (SHA-256 wie angezeigt) als Beleg ohne Dokumentart in
    **einem** Vorgang auf; keine Einlese-Regel, kein Claude. Eine Datei, deren Inhalt nicht mehr
    der angezeigte ist, fehlt oder schon aufgenommen ist, wird übersprungen und gemeldet. Wird
    nichts aufgenommen, ist das Ergebnis die Abweisung; weist der Schreibweg ab, bleibt nichts."""
    taken: list[Document] = []
    changes: list[Change] = []
    skipped: list[tuple[SiteFile, str]] = []
    seen: set[str] = set()
    for file in files:
        prepared = (
            IntakeRejected((ALREADY_TAKEN_IN,))
            if file.sha256 in seen
            else _intake(
                store, {}, user, file.site, file.path, "", DEFAULT_YEAR, expected_sha256=file.sha256
            )
        )
        if isinstance(prepared, IntakeRejected):
            skipped.append((file, " ".join(prepared.reasons)))
            continue
        seen.add(file.sha256)
        document, _, document_changes = prepared
        taken.append(document)
        changes.extend(document_changes)
    if not taken:
        return IntakeRejected(
            tuple(f"{file.path}: {reason}" for file, reason in skipped) or (NO_FILES,)
        )
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return IntakeRejected(tuple(result.reasons.values()))
    return TakenInAll(tuple(taken), tuple(skipped))


def change_document(
    store: Store,
    kinds: Mapping[str, DocumentKind],
    document: Document,
    issuer: EntryAddress | None,
    issuer_changes: Sequence[Change] = (),
    kind_key: str | None = None,
    year: int | None = None,
    *,
    label: str | None | EllipsisType = ...,
    values_on: Callable[[State], "Values"] | None = None,
) -> Applied | IntakeRejected:
    """Ändert das Dokument: Aussteller und Bezeichnung immer, Art und Jahr nur, solange nichts
    daran hängt. Ohne `label` (`...`) bleibt die Bezeichnung, `None` entfernt sie.

    `kind_key` (leer = Beleg) und `year` sind nur beim Ändern von Art oder Jahr angegeben;
    hängt etwas am Dokument, sind sie ein Fehler. Wechselt die Art, wird das Dokument nach ihrer
    Einlese-Regel neu eingelesen, und ihre Ergänzung beim Aufnehmen läuft (`values_on`): Art
    später setzen tut dasselbe wie Aufnehmen mit Art.
    """
    state = store.state()
    update: dict[str, object] = {"issuer": issuer}
    if not isinstance(label, EllipsisType):
        update["label"] = label
    updated = document.model_copy(update=update)
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
                entries = _read_in(kind, updated, content)
                changes.extend(Put(entry) for entry in entries)
                # der Schnappschuss trägt den Zeitpunkt des Setzens der Art, nicht den des Belegs
                setting = updated.model_copy(
                    update={"taken_in_at": datetime.datetime.now(datetime.UTC)}
                )
                changes.extend(
                    _after_take_in(kind, store, setting, entries, values_on, [updated, *entries])
                )
            except (SiteFileError, ReadInError) as error:
                return IntakeRejected((str(error),))
    changes.append(Put(updated, entry_checksum(document)))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return _rejected(result.reasons, state, kinds, updated, changes)
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


def _is_sensitive(kind: str, entry: ReadInEntry, where: str) -> bool:
    """Ob die Stelle `where` (Art + Pfad im Eintrag) in einem sensiblen Feld des Eintrags liegt."""
    return any(
        where == f"{kind}.{name}" or where.startswith((f"{kind}.{name}.", f"{kind}.{name}["))
        for name in entry.sensitive_fields
    )


def _shown(kind: str, entry: ReadInEntry, where: str, text: str | None) -> str | None:
    """Der Wert, wie ihn die Neueinlesung festhält: ein sensibler nie, nur dass es ihn gibt."""
    if text is not None and _is_sensitive(kind, entry, where):
        return SENSITIVE_SHOWN
    return _clip(text)


def _clip(text: str | None) -> str | None:
    return None if text is None else text[:TEXT_MAX]


def _field_differences(
    kind: str, before: ReadInEntry, after: ReadInEntry
) -> list[ReadInDifference]:
    old, new = _values(kind, before), _values(kind, after)
    return [
        ReadInDifference(
            location=_clip(where) or kind,
            before=_shown(kind, before, where, old.get(where)),
            after=_shown(kind, after, where, new.get(where)),
        )
        for where in dict.fromkeys((*old, *new))
        if old.get(where) != new.get(where)
    ]


def _entry_differences(
    kind: str, before: Sequence[ReadInEntry], after: Sequence[ReadInEntry]
) -> list[ReadInDifference]:
    """Einträge als Ganzes: was nur vorher bzw. nur nachher vorkommt."""

    def text(entry: ReadInEntry) -> str:
        shown = {
            where: _shown(kind, entry, where, value)
            for where, value in _values(kind, entry).items()
        }
        return json.dumps(shown, ensure_ascii=False, sort_keys=True)

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
    sites: Sites,
) -> list[Finding]:
    """Ein Hinweis je Neueinlesung des Nutzers, deren Dokument zum Jahr gehört (`belongs_to_year`).

    Der Link führt zum ersten
    eingelesenen Eintrag des Dokuments, wenn sein Modul eine Seite dafür hat (die Anbindung löst das
    Ziel auf).
    """
    found: list[Finding] = []
    for rereading in sorted(state.of_kind(Rereading), key=lambda r: (r.reread_at, r.id)):
        document = state.get(rereading.document)
        if rereading.owner != user or not isinstance(document, Document):
            continue
        if not belongs_to_year(document, year, state, sites):
            continue
        title = kind_title(kinds, document.document_kind) or "Dokument"
        shown = "; ".join(_describe(d) for d in rereading.differences[:SHOWN_DIFFERENCES])
        more = rereading.difference_count - min(SHOWN_DIFFERENCES, len(rereading.differences))
        message = (
            f"{title} {document.path}: Neues Einlesen (Fassung {rereading.version_before} → "
            f"{rereading.version_after}) hat {rereading.difference_count} Stelle(n) geändert: "
            f"{shown}" + (f" und {more} weitere." if more > 0 else ".")
        )
        found.append(Finding(READ_IN_CHANGED, Severity.NOTE, rereading.address, message))
    return found


def _describe(difference: ReadInDifference) -> str:
    def quoted(text: str | None) -> str:
        return "nicht vorhanden" if text is None else f"„{text}“"

    return f"{difference.location} {quoted(difference.before)} → {quoted(difference.after)}"
