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
from moarcoal.extraction import Extracted, ExtractedField, ExtractionFailed, Extractor
from moarcoal.storage import (
    Applied,
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

DEFAULT_MEDIA_TYPE = "application/octet-stream"


@dataclass(frozen=True)
class ReadOutRejected:
    """Es entstand kein Vorschlag; `message` ist für den Nutzer."""

    message: str


def document_url(document: Document) -> str:
    return f"/dokumente/{document.id}"


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

    Ein zweiter Vorschlag zum selben Dokument entsteht hier nicht (Neu auslesen kommt später).
    """
    kind = kinds.get(document.document_kind or "")
    template = None if kind is None else kind.extraction_template
    if template is None:
        return ReadOutRejected("Diese Dokumentart kann nicht ausgelesen werden.")
    if proposals_of(store.state(), document):
        return ReadOutRejected("Zu diesem Dokument gibt es schon einen Vorschlag.")
    try:
        content = store.read_site_file(document.site, document.path)
    except SiteFileError as error:
        return ReadOutRejected(str(error))
    if hashlib.sha256(content).hexdigest() != document.sha256:
        return ReadOutRejected("Die Datei hat sich seit dem Aufnehmen geändert.")
    media_type = mimetypes.guess_type(document.path)[0] or DEFAULT_MEDIA_TYPE
    answer = extractor.extract(content, media_type, template.json_schema(), template.hint())
    if isinstance(answer, ExtractionFailed):
        return ReadOutRejected(answer.message)
    proposal = _proposal(user, document, template.version, [f.key for f in template.fields], answer)
    result = store.apply([Put(proposal)])
    if not isinstance(result, Applied):
        return ReadOutRejected(" ".join(result.reasons.values()))
    return proposal


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
    store: Store, proposal: Proposal, key: str | None, correction: str | None = None
) -> Applied | ReadOutRejected:
    """Bestätigt das Feld `key` (mit Korrektur, wenn angegeben) oder, ohne `key`, alle offenen.

    Eine leere Korrektur bestätigt den ausgelesenen Inhalt. Der ausgelesene Inhalt bleibt in
    jedem Fall am Feld stehen.
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
    for proposal in sorted(state.of_kind(Proposal), key=lambda p: str(p.address)):
        document = documents.get(proposal.document)
        if proposal.owner != user or document is None:
            continue
        if (
            document.period_start is not None
            and document.period_end is not None
            and not document.period_start.year <= year <= document.period_end.year
        ):
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
                href=document_url(document),
                fingerprint=fingerprint(*open_keys),
            )
        )
    return found


def document_of(state: State, user: str, document_id: str) -> Document | None:
    entry = state.get(EntryAddress(kind=Document.__name__, id=document_id))
    return entry if isinstance(entry, Document) and entry.owner == user else None
