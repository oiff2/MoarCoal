"""Modulanmeldung und eingegrenzter Stand eines Moduls (docs/grundgeruest.md, 3.4 und 4)."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from moarcoal.documents import DocumentKind
from moarcoal.extraction_template import Confirmed
from moarcoal.proposals import latest_proposal, template_of
from moarcoal.storage import (
    Document,
    Entry,
    EntryAddress,
    EntryKind,
    Proposal,
    Snapshot,
    State,
    Store,
    entry_checksum,
    open_store,
)
from moarcoal.values.calculation import ValueSource
from moarcoal.values.catalog import ValueDefinition
from moarcoal.values.findings import Finding, FindingKind
from moarcoal.values.model import DocumentLocator, Source, Subject, TimeRef, ValueKey

type FindingSource = Callable[[ModuleState, ValueSource, int], Iterable[Finding]]
"""Befunde eines Moduls für ein Jahr: eigener Stand, Werte (auch fremde) und das Jahr."""


@dataclass(frozen=True)
class ModuleRegistration:
    """Was ein Modul beim Start über sich bekannt gibt: Schlüssel, Name, Seiten, Arten, Werte.

    Je Art nennt `kinds` Dateiformat und die Funktion Eintrag -> Pfad; die Datenebene lädt und
    schreibt danach, das Modul fasst keine Datei an.
    """

    key: str
    area_name: str
    nav_label: str
    nav_url: str
    router: APIRouter
    kinds: tuple[EntryKind, ...]
    icon: str = "modul"  # Datei `templates/icons/<icon>.svg`, Icon in der Seitenleiste
    values: tuple[ValueDefinition, ...] = ()
    entry_url: Callable[[EntryAddress], str | None] = lambda address: None
    # Wo man erfasst, woraus ein eigener Schlüssel rechnet: (Beschriftung, Adresse) oder `None`;
    # Vorauswahl Zeitbezug und Bezugsobjekt, nie ein Feld eines anderen Moduls (#176). Der Stand
    # des Moduls zeigt, ob es den Beleg schon gibt (dann führt die Adresse zu ihm, #181).
    capture_url: Callable[
        [ValueKey, TimeRef, Subject | None, "ModuleState"], tuple[str, str] | None
    ] = lambda key, time, subject, state: None
    document_kinds: tuple[DocumentKind, ...] = ()
    finding_kinds: tuple[FindingKind, ...] = ()
    findings: FindingSource | None = None


class ForeignKindError(LookupError):
    """Ein Modul hat nach einer Art gefragt, die ihm nicht gehört (Programmfehler)."""


class ModuleState:
    """Stand, eingegrenzt auf ein Modul und einen Nutzer; nur lesen."""

    def __init__(self, state: State, registration: ModuleRegistration, user: str) -> None:
        self._state = state
        self._kinds = {kind.model.__name__ for kind in registration.kinds}
        self._document_kinds = {kind.key: kind for kind in registration.document_kinds}
        self._user = user
        self._module = registration.key

    @property
    def user(self) -> str:
        return self._user

    def _own(self, kind_name: str) -> None:
        if kind_name not in self._kinds:
            raise ForeignKindError(f"Art {kind_name} gehört nicht zu diesem Modul")

    def all[E: Entry](self, kind: type[E]) -> list[E]:
        """Alle Einträge einer eigenen Art des Nutzers, nach Adresse sortiert."""
        self._own(kind.__name__)
        found = [e for e in self._state.of_kind(kind) if e.owner == self._user]
        return sorted(found, key=lambda e: str(e.address))

    def get(self, address: EntryAddress) -> Entry | None:
        """Ein eigener Eintrag des Nutzers; Einträge anderer Nutzer gibt es hier nicht."""
        self._own(address.kind)
        entry = self._state.get(address)
        return entry if entry is not None and entry.owner == self._user else None

    def documents(self, document_kind: str | None = None) -> list[Document]:
        """Dokumente des Nutzers (Baustein der Datenebene), ggf. nur einer Dokumentart."""
        found = [d for d in self._state.of_kind(Document) if d.owner == self._user]
        if document_kind is not None:
            found = [d for d in found if d.document_kind == document_kind]
        return sorted(found, key=lambda d: str(d.address))

    def latest_proposal(self, document: Document) -> Proposal | None:
        """Der neueste Vorschlag zu einem Dokument des Nutzers; Dokumente anderer Nutzer: `None`."""
        return latest_proposal(self._state, document) if document.owner == self._user else None

    def confirmed_fields(self, document: Document) -> dict[str, tuple[Confirmed, DocumentLocator]]:
        """Die bestätigten Felder des neuesten Vorschlags zum Dokument (Spec 3.6, Punkt 9).

        Je Feldschlüssel der Inhalt (bei einer Korrektur der korrigierte) und die Fundstelle mit
        Belegstand belegt; unbestätigte Felder fehlen. Dokumente anderer Nutzer: leer. Ausgelesen
        oder korrigiert, der Inhalt hat dieselbe Form: ein Feld mit Einheit kommt als `Decimal`
        (`TemplateField.read`); ein Feld, dessen Inhalt das nicht zulässt, fehlt (Bestätigen weist
        es ab, das trifft nur Vorschläge von vorher).
        """
        latest = self.latest_proposal(document)
        if latest is None:
            return {}
        template = template_of(self._document_kinds, document)
        found: dict[str, tuple[Confirmed, DocumentLocator]] = {}
        for key, field in latest.fields.items():
            if not field.confirmed:
                continue
            spec = None if template is None else template.field(key)
            try:
                content = field.content if spec is None else spec.read(field.content)
            except ValueError:
                continue
            locator = DocumentLocator(
                document.address, Source.DOCUMENT_EXTRACTION, key, field.location
            )
            found[key] = (content, locator)
        return found

    def snapshots(self) -> list[Snapshot]:
        """Schnappschüsse des Nutzers, die dieses Modul ausgelöst hat (Baustein der Datenebene)."""
        found = [
            s
            for s in self._state.of_kind(Snapshot)
            if s.owner == self._user and s.module == self._module
        ]
        return sorted(found, key=lambda s: (s.taken_at, s.id))

    def checksum(self, address: EntryAddress) -> str | None:
        entry = self.get(address)
        return None if entry is None else entry_checksum(entry)


def open_module_store(data_dir: Path, modules: Sequence[ModuleRegistration]) -> Store:
    """Öffnet das Datenverzeichnis mit den Eintrags- und Dokumentarten der Module; so öffnen es
    die App und jedes Werkzeug, das über `apply` schreibt."""
    return open_store(
        data_dir,
        [kind for module in modules for kind in module.kinds],
        once_per_period={
            kind.key: kind.title
            for module in modules
            for kind in module.document_kinds
            if kind.unique_per_period
        },
        kinds_with_period={k.key for m in modules for k in m.document_kinds if k.has_period},
    )
