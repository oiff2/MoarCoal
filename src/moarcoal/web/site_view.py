"""Seitenmodell der Belege-Seite eines Jahrs: die drei Abschnitte als reine Funktionen.

Was offen ist und wie man ausblendet, steht in `incoming.py`, zu welchem Jahr ein Dokument
gehört in `documents.py`, wann ein Erwarteter Beleg erfüllt ist in `expected_documents.py`;
hier steht, wie die Seite es zeigt.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from moarcoal.document_filter import (
    DocumentState,
    FileType,
    SearchFilter,
    document_state,
    file_type,
)
from moarcoal.documents import DocumentKind, belongs_to_year, document_name
from moarcoal.expected_documents import matching_documents, previous_year_issuer
from moarcoal.incoming import hidden_files, hidden_folders, in_hidden_folder, incoming_files
from moarcoal.storage import (
    Document,
    EntryAddress,
    ExpectedDocument,
    HiddenFile,
    HiddenFolder,
    Issuer,
    SiteFile,
    Sites,
    State,
    entry_checksum,
)
from moarcoal.web.links import document_url, site_file_url, with_filter


@dataclass(frozen=True)
class NewFile:
    """Eine Zeile im Abschnitt Neu: eine Datei des Eingangs."""

    file: SiteFile

    @property
    def name(self) -> str:
        return self.file.path.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        """Der Ordner der Datei im Ablageort; leer, wenn sie dort lose liegt."""
        return self.file.path.rpartition("/")[0]

    @property
    def preview_url(self) -> str:
        return site_file_url(self.file.sha256)


@dataclass(frozen=True)
class DuplicateHint:
    """Ein Hinweis im Abschnitt Neu: die Datei hat denselben Inhalt wie ein aufgenommenes
    Dokument und wird nicht noch einmal aufgenommen."""

    file: SiteFile
    document: Document
    document_name: str
    document_url: str

    @property
    def name(self) -> str:
        return self.file.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class NewGroup:
    """Der Eingang eines Ablageorts."""

    site: str
    files: list[NewFile]


@dataclass(frozen=True)
class HiddenFileRow:
    """Eine Zeile im Abschnitt „Ausgeblendet“: die Ausblendung, ihre Prüfsumme und die Datei,
    falls sie noch in einem Ablageort liegt (sonst keine Größe und keine Vorschau)."""

    entry: HiddenFile
    checksum: str
    file: SiteFile | None

    @property
    def path(self) -> str:
        return self.entry.path

    @property
    def preview_url(self) -> str:
        return site_file_url(self.entry.sha256) if self.file else ""


@dataclass(frozen=True)
class HiddenFolderRow:
    """Ein ausgeblendeter Ordner mit seiner Prüfsumme und der Zahl der Dateien darunter."""

    entry: HiddenFolder
    checksum: str
    count: int


@dataclass(frozen=True)
class NewSection:
    """Der Abschnitt „Neu im Jahresordner“: der Eingang des Jahresordners (falls es ihn gibt),
    darunter die Ablageorte ohne Jahr, dazu die Ausblendungen dieser Ablageorte."""

    year: int
    year_folder: str | None
    groups: list[NewGroup]
    duplicates: list[DuplicateHint]
    hidden_files: list[HiddenFileRow]
    hidden_folders: list[HiddenFolderRow]

    @property
    def sites(self) -> list[str]:
        return [g.site for g in self.groups]

    def files(self) -> list[NewFile]:
        """Alle Dateien des Abschnitts in der Reihenfolge der Anzeige."""
        return [f for g in self.groups for f in g.files]

    def open_file(self, sha256: str) -> SiteFile | None:
        return next((f.file for f in self.files() if f.file.sha256 == sha256), None)

    def hidden_file(self, sha256: str) -> HiddenFileRow | None:
        return next((h for h in self.hidden_files if h.entry.sha256 == sha256), None)


def next_open(shas: Sequence[str], sha256: str) -> str | None:
    """SHA-256 der nächsten Datei nach `sha256` in `shas`, am Ende von vorn; ohne weitere `None`."""
    start = shas.index(sha256) + 1 if sha256 in shas else 0
    others = [s for s in [*shas[start:], *shas[:start]] if s != sha256]
    return others[0] if others else None


def duplicate_hints(
    files: Sequence[SiteFile], ordered: Sequence[SiteFile], state: State, user: str
) -> list[DuplicateHint]:
    """Je nicht ausgeblendeter Datei in `ordered`, deren Inhalt (SHA-256) ein Dokument von `user`
    schon hat, ein Hinweis auf dieses Dokument (bei mehreren das erste nach Pfad). Die Datei, die
    das Dokument selbst ist (Ablageort und Pfad), bekommt keinen; ebenso keine im Ablageort des
    Dokuments, wenn dessen Datei dort fehlt (sie wurde verschoben, `relocate_documents` führt den
    Pfad beim Start nach)."""
    present = {(f.site, f.path, f.sha256) for f in files}
    documents: dict[str, Document] = {}
    for d in sorted(state.of_kind(Document), key=lambda d: (d.path, d.site, d.id)):
        if d.owner == user:
            documents.setdefault(d.sha256, d)
    hidden = {h.sha256 for h in state.of_kind(HiddenFile)}
    folders = state.of_kind(HiddenFolder)
    return [
        DuplicateHint(f, d, document_name(d, state), document_url(d.id))
        for f in ordered
        if (d := documents.get(f.sha256)) is not None
        and (f.site, f.path) != (d.site, d.path)
        and ((d.site, d.path, d.sha256) in present or f.site != d.site)
        and f.sha256 not in hidden
        and not in_hidden_folder(f, folders)
    ]


def new_section(
    files: Sequence[SiteFile], sites: Sites, state: State, user: str, year: int
) -> NewSection:
    """Der Abschnitt Neu von `user` für `year`: der Jahresordner zuerst, dann die Ablageorte
    ohne Jahr (nach Name). Ablageorte, die zu einem anderen Jahr gehören, fehlen."""
    year_folder = sites.year_folder(year)
    shown = ([year_folder] if year_folder else []) + [
        s for s in sites.names() if sites.year_of(s) is None
    ]
    ordered = [f for site in shown for f in files if f.site == site]  # erster Ort gewinnt
    open_files = incoming_files(ordered, state, user)
    taken = {d.sha256 for d in state.of_kind(Document) if d.owner == user}
    return NewSection(
        year=year,
        year_folder=year_folder,
        groups=[
            NewGroup(site, [NewFile(f) for f in open_files if f.site == site]) for site in shown
        ],
        duplicates=duplicate_hints(files, ordered, state, user),
        hidden_files=[
            HiddenFileRow(
                h, entry_checksum(h), next((f for f in files if f.sha256 == h.sha256), None)
            )
            for h in hidden_files(state)
            if h.site in shown and h.sha256 not in taken
        ],
        hidden_folders=[
            HiddenFolderRow(h, entry_checksum(h), sum(1 for f in files if in_hidden_folder(f, [h])))
            for h in hidden_folders(state)
            if h.site in shown
        ],
    )


@dataclass(frozen=True)
class ExpectedRow:
    """Eine Zeile im Abschnitt Erwartete Belege: der Eintrag, sein Aussteller (der des erfüllenden
    Dokuments, sonst der des Vorjahrs) und die Dokumente, die ihn im Jahr erfüllen."""

    entry: ExpectedDocument
    title: str
    issuer: Issuer | None
    documents: tuple[Document, ...]
    checksum: str

    @property
    def pending(self) -> bool:
        return not self.documents


def expected_rows(
    state: State, user: str, year: int, kinds: Mapping[str, DocumentKind]
) -> list[ExpectedRow]:
    """Die Erwarteten Belege von `user`, die in `year` fällig sind, nach Beginn und Kennung."""
    documents = [d for d in state.of_kind(Document) if d.owner == user]
    rows: list[ExpectedRow] = []
    for entry in sorted(state.of_kind(ExpectedDocument), key=lambda e: (e.start_year, e.id)):
        if entry.owner != user or not entry.due_in(year):
            continue
        found = tuple(matching_documents(documents, entry, year))
        address = next((d.issuer for d in found if d.issuer), None) or previous_year_issuer(
            documents, entry, year
        )
        issuer = None if address is None else state.get(address)
        kind = kinds.get(entry.document_kind)
        rows.append(
            ExpectedRow(
                entry,
                kind.title if kind else entry.document_kind,
                issuer if isinstance(issuer, Issuer) else None,
                found,
                entry_checksum(entry),
            )
        )
    return rows


@dataclass(frozen=True)
class DocumentRow:
    """Eine Zeile im Abschnitt Aufgenommene Belege."""

    document: Document
    kind: str  # Titel der Dokumentart mit Bezugsjahr; leer bei einem Beleg ohne Art
    state: DocumentState


def year_documents(
    state: State, sites: Sites, kinds: Mapping[str, DocumentKind], user: str, year: int
) -> list[DocumentRow]:
    """Die Dokumente von `user`, die zu `year` gehören (`belongs_to_year`), nach Pfad."""
    chosen = sorted(
        (
            d
            for d in state.of_kind(Document)
            if d.owner == user and belongs_to_year(d, year, state, sites)
        ),
        key=lambda d: (d.path, d.site, d.id),
    )
    rows: list[DocumentRow] = []
    for document in chosen:
        kind = kinds.get(document.document_kind or "")
        title = kind.title if kind else (document.document_kind or "")
        if title and document.period_start:
            title = f"{title}, {document.period_start.year}"
        rows.append(DocumentRow(document, title, document_state(state, kinds, document)))
    return rows


def _issuer_name(state: State, issuer: EntryAddress | None) -> str:
    found = state.get(issuer) if issuer else None
    return found.name if isinstance(found, Issuer) else ""


def filter_new(section: NewSection, flt: SearchFilter) -> NewSection:
    """Der Abschnitt Neu mit den Dateien, die Suche (Ablageort, Pfad mit Ordner und Name) und
    Dateityp treffen, ebenso die Hinweise auf gleichen Inhalt. Die Ausblendungen bleiben stehen:
    sie sind eine Pflegeliste."""
    return replace(
        section,
        groups=[
            NewGroup(
                g.site,
                [
                    f
                    for f in g.files
                    if flt.matches([f.file.site, f.file.path], [file_type(f.file.path)])
                ],
            )
            for g in section.groups
        ],
        duplicates=[
            replace(h, document_url=with_filter(h.document_url, flt))
            for h in section.duplicates
            if flt.matches([h.file.site, h.file.path], [file_type(h.file.path)])
        ],
    )


def filter_expected(rows: Sequence[ExpectedRow], flt: SearchFilter) -> list[ExpectedRow]:
    """Die Erwarteten Belege, die Suche (Belegtyp, Beschreibung, Aussteller) und Dateityp treffen;
    ein Dateityp haben nur die Dokumente, die den Eintrag erfüllen, ein ausstehender keinen."""
    return [
        r
        for r in rows
        if flt.matches(
            [r.title, r.entry.description or "", r.issuer.name if r.issuer else ""],
            [file_type(d.path) for d in r.documents],
        )
    ]


def filter_documents(
    rows: Sequence[DocumentRow], flt: SearchFilter, state: State
) -> list[DocumentRow]:
    """Die Aufgenommenen Belege, die Suche (Ablageort, Pfad, Name, Bezeichnung, Aussteller) und
    Dateityp treffen."""
    return [
        r
        for r in rows
        if flt.matches(
            [
                r.document.site,
                r.document.path,
                document_name(r.document, state),
                r.document.label or "",
                _issuer_name(state, r.document.issuer),
            ],
            [file_type(r.document.path)],
        )
    ]


def type_counts(
    new: NewSection, documents: Sequence[DocumentRow], flt: SearchFilter, state: State
) -> dict[FileType, int]:
    """Wie viele Dateien (Neu und Aufgenommen) je Dateityp die Suche trifft; die Wahl der
    Dateitypen bleibt außen vor, sonst zeigte jeder Typ nur „0“, sobald ein anderer gewählt ist."""
    search = flt.without_types()
    paths = [f.file.path for f in filter_new(new, search).files()]
    paths += [r.document.path for r in filter_documents(documents, search, state)]
    counts = Counter(file_type(p) for p in paths)
    return {t: counts[t] for t in FileType}
