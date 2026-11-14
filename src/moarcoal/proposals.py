"""Auslesen als Vorschlag: auslesen, bestätigen und der Befund „Unbestätigter Vorschlag“ (Spec 3.6).

Ausgelesen wird nur auf Wunsch, je Dokument. Fehlschlag heißt: kein Vorschlag, nur eine Meldung.
Bestätigungen und Korrekturen stehen am Vorschlag; die Module lesen sie über
`ModuleState.confirmed_fields`, nichts wird in Moduleinträge kopiert.
"""

import datetime
import hashlib
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass

from moarcoal.documents import DocumentKind
from moarcoal.extraction import (
    CLAUDE_TOOLS,
    Extracted,
    ExtractedField,
    ExtractionFailed,
    Extractor,
    FailureReason,
)
from moarcoal.extraction_template import ExtractionTemplate
from moarcoal.storage import (
    AbortedExtraction,
    Applied,
    Delete,
    Document,
    EntryAddress,
    Proposal,
    ProposalField,
    Put,
    SiteFileError,
    State,
    Store,
)
from moarcoal.values.findings import Finding, Severity, fingerprint

UNCONFIRMED = "unconfirmed_proposal"
"""Befundart „Unbestätigter Vorschlag“ (Hinweis)."""

NOT_RECORDED = "Der Abbruch konnte nicht festgehalten werden; es gibt dazu keinen Fehler-Befund."

DEFAULT_MEDIA_TYPE = "application/octet-stream"


@dataclass(frozen=True)
class ReadOutRejected:
    """Es entstand kein Vorschlag; `message` ist für den Nutzer."""

    message: str


def proposals_of(state: State, document: Document) -> list[Proposal]:
    """Die Vorschläge des Eigentümers zum Dokument, der neueste zuletzt."""
    found = [
        p
        for p in state.of_kind(Proposal)
        if p.owner == document.owner and p.document == document.address
    ]
    return sorted(found, key=lambda p: (p.created_at, p.id))


def read_out(
    store: Store,
    extractor: Extractor,
    kinds: Mapping[str, DocumentKind],
    user: str,
    document: Document,
) -> Proposal | ReadOutRejected:
    """Liest `document` nach der Auslese-Vorlage seiner Art aus und legt den Vorschlag an.

    Gibt es schon einen Vorschlag, entsteht ein neuer daneben (Neu auslesen); der neueste gilt,
    Bestätigungen des alten werden nicht übernommen. Ein Fehlschlag legt nichts an.
    """
    kind = kinds.get(document.document_kind or "")
    template = None if kind is None else kind.extraction_template
    if template is None:
        return ReadOutRejected("Diese Dokumentart kann nicht ausgelesen werden.")
    try:
        content = store.read_site_file(document.site, document.path)
    except SiteFileError as error:
        return ReadOutRejected(str(error))
    if hashlib.sha256(content).hexdigest() != document.sha256:
        return ReadOutRejected("Die Datei hat sich seit dem Aufnehmen geändert.")
    media_type = mimetypes.guess_type(document.path)[0] or DEFAULT_MEDIA_TYPE
    answer = extractor.extract(content, media_type, template.json_schema(), template.hint())
    state = store.state()
    aborted = aborted_of(state, document)
    if isinstance(answer, ExtractionFailed):
        tools = answer.reason is FailureReason.TOOLS_REPORTED
        if tools and not _record_abort(store, state, user, document, aborted):
            return ReadOutRejected(f"{answer.message} {NOT_RECORDED}")
        return ReadOutRejected(answer.message)
    proposal = _proposal(user, document, template.version, [f.key for f in template.fields], answer)
    changes: list[Put | Delete] = [Put(proposal)]
    if aborted is not None:  # gelungen: die Abgebrochene Auslesung ist geklärt
        changes.append(Delete(aborted.address, expected=state.checksum(aborted.address) or ""))
    result = store.apply(changes)
    if not isinstance(result, Applied):
        return ReadOutRejected(" ".join(result.reasons.values()))
    return proposal


def aborted_of(state: State, document: Document) -> AbortedExtraction | None:
    """Die Abgebrochene Auslesung des Dokuments, falls festgehalten (höchstens eine)."""
    return next(
        (
            a
            for a in state.of_kind(AbortedExtraction)
            if a.owner == document.owner and a.document == document.address
        ),
        None,
    )


def _record_abort(
    store: Store, state: State, user: str, document: Document, old: AbortedExtraction | None
) -> bool:
    """Hält den Abbruch fest; ein früherer Eintrag desselben Dokuments wird ersetzt."""
    now = datetime.datetime.now(datetime.UTC)
    if old is None:
        change = Put(AbortedExtraction(owner=user, document=document.address, aborted_at=now))
    else:
        replaced = old.model_copy(update={"aborted_at": now})
        change = Put(replaced, expected=state.checksum(old.address))
    return isinstance(store.apply([change]), Applied)


def aborted_extraction_findings(state: State, user: str) -> list[Finding]:
    """Fehler je Abgebrochener Auslesung, in jedem Jahr (ein Sicherheitsfehler darf nicht fehlen).

    Ziel ist das Dokument; der Fingerabdruck nennt den Zeitpunkt des Abbruchs, ein neuer Abbruch
    bringt also einen ausgeblendeten Befund zurück.
    """
    documents = {d.address: d for d in state.of_kind(Document) if d.owner == user}
    found: list[Finding] = []
    for aborted in sorted(state.of_kind(AbortedExtraction), key=lambda a: str(a.document)):
        document = documents.get(aborted.document)
        if aborted.owner != user or document is None:
            continue
        text = (
            f"Claude-Aufruf meldet Werkzeuge oder MCP-Server; die Auslesung von {document.path} "
            "wurde abgebrochen."
        )
        found.append(
            Finding(
                CLAUDE_TOOLS,
                Severity.ERROR,
                document.address,
                text,
                href=document.url,
                fingerprint=fingerprint(aborted.aborted_at.isoformat()),
            )
        )
    return found


def _proposal(
    user: str, document: Document, version: int, keys: list[str], answer: Extracted
) -> Proposal:
    """Nur Felder der Vorlage, in ihrer Reihenfolge; ein fehlendes Feld ist leer."""
    fields = {
        key: ProposalField(value=given.value, location=given.location)
        for key in keys
        for given in [answer.fields.get(key, ExtractedField(value=None, location=""))]
    }
    return Proposal(
        owner=user,
        document=document.address,
        template_version=version,
        fields=fields,
        raw=answer.raw,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def confirm(
    store: Store,
    proposal: Proposal,
    template: ExtractionTemplate | None,
    key: str | None,
    correction: str | None = None,
) -> Applied | ReadOutRejected:
    """Bestätigt das Feld `key` (mit Korrektur, wenn angegeben) oder, ohne `key`, alle offenen.

    Eine leere Korrektur bestätigt den ausgelesenen Inhalt. Der ausgelesene Inhalt bleibt in
    jedem Fall am Feld stehen. Ein Feld mit Einheit lässt sich nur mit einer Zahl (oder leer)
    bestätigen, damit `confirmed_fields` je Feld dieselbe Form liefert (`TemplateField.read`).
    """
    fields = dict(proposal.fields)
    if key is None:
        for name, field in fields.items():
            if not field.confirmed:
                fields[name] = field.model_copy(update={"confirmed": True})
    else:
        field = fields.get(key)
        if field is None:
            return ReadOutRejected("Das Feld gibt es in diesem Vorschlag nicht.")
        text = (correction or "").strip()
        fields[key] = field.model_copy(
            update={"confirmed": True, "correction": text if text else None}
        )
    problems: list[str] = []
    for name, field in fields.items():
        spec = None if template is None else template.field(name)
        if spec is None or field is proposal.fields[name]:
            continue  # unverändert oder ohne Vorlage
        try:
            spec.read(field.content)
        except ValueError as error:
            problems.append(str(error))
    if problems:
        return ReadOutRejected(" ".join(problems))
    changed = proposal.model_copy(update={"fields": fields})
    result = store.apply([Put(changed, expected=store.state().checksum(proposal.address))])
    if not isinstance(result, Applied):
        return ReadOutRejected(" ".join(result.reasons.values()))
    return result


def proposal_findings(
    state: State, user: str, year: int, titles: Mapping[str, str]
) -> list[Finding]:
    """Hinweis je Vorschlag mit offenen Feldern, für Dokumente des Jahrs oder ohne Bezugszeitraum.

    Der Fingerabdruck nennt die offenen Felder; bestätigt der Nutzer eines, kehrt ein
    ausgeblendeter Hinweis zurück.
    """
    documents = {d.address: d for d in state.of_kind(Document) if d.owner == user}
    found: list[Finding] = []
    for document in sorted(documents.values(), key=lambda d: str(d.address)):
        history = proposals_of(state, document)
        if not history:
            continue
        proposal = history[-1]  # nur der neueste Vorschlag zählt
        if document.period_start is not None and not document.touches_year(year):
            continue
        open_keys = proposal.open_keys
        if not open_keys:
            continue
        title = titles.get(document.document_kind or "", document.document_kind or "Dokument")
        text = (
            f"Unbestätigter Vorschlag zu {title} {document.path}: "
            f"{len(open_keys)} von {len(proposal.fields)} Feldern offen"
        )
        found.append(
            Finding(
                UNCONFIRMED,
                Severity.NOTE,
                proposal.address,
                text,
                href=document.url,
                fingerprint=fingerprint(*open_keys),
            )
        )
    return found


def document_of(state: State, user: str, document_id: str) -> Document | None:
    entry = state.get(EntryAddress(kind=Document.__name__, id=document_id))
    return entry if isinstance(entry, Document) and entry.owner == user else None
