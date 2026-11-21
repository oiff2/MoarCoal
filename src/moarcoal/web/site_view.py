"""Seitenmodell der Belege-Seite eines Jahrs: die drei Abschnitte als reine Funktionen.

Was offen ist und wie man ausblendet, steht in `incoming.py`, zu welchem Jahr ein Dokument
gehört in `documents.py`, wann ein Erwarteter Beleg erfüllt ist in `expected_documents.py`;
hier steht, wie die Seite es zeigt.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from moarcoal.document_filter import DocumentState, document_state
from moarcoal.documents import DocumentKind, belongs_to_year
from moarcoal.expected_documents import matching_documents, previous_year_issuer
from moarcoal.incoming import hidden_files, hidden_folders, in_hidden_folder, incoming_files
from moarcoal.storage import (
    Document,
    ExpectedDocument,
    HiddenFile,
    HiddenFolder,
    Issuer,
    SiteFile,
    Sites,
    State,
    entry_checksum,
)
from moarcoal.web.links import site_file_url


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
