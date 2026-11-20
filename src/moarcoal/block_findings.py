"""Befunde der Bausteine der Datenebene (Belege, Aussteller): eine Sammelfunktion für `Values`.

`Values.finding_list` kennt die Bausteine nicht einzeln; es ruft nur `block_findings`.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from moarcoal.documents import DocumentKind, duplicate_findings, rereading_findings
from moarcoal.expected_documents import expected_document_findings
from moarcoal.incoming import incoming_files
from moarcoal.issuers import issuer_findings
from moarcoal.proposals import aborted_extraction_findings, proposal_findings
from moarcoal.storage import SiteFile, State
from moarcoal.values.findings import INCOMING_FILES, Finding, Severity, fingerprint


class BlockFindings(NamedTuple):
    """Die Befunde in der Reihenfolge, in der `Values` sie einreiht: `early` vor den Befunden der
    Sperrliste, `late` danach (beide vor Schnappschüssen und Modulen), `incoming` ganz zum Schluss.
    Bei gleichem Schweregrad bleibt diese Reihenfolge sichtbar."""

    early: list[Finding]
    late: list[Finding]
    incoming: list[Finding]


def block_findings(
    state: State,
    user: str,
    year: int,
    kinds: Mapping[str, DocumentKind],
    site_files: Callable[[], Sequence[SiteFile]] | None,
) -> BlockFindings:
    """Alle Befunde der Bausteine für `user` und `year`: Erwartete Belege, Aussteller, Dokumente
    (Dubletten, Neueinlesung), Vorschläge, Abgebrochene Auslesungen und der Eingang (nur mit
    `site_files`, den Dateien der Ablageorte)."""
    titles = {key: kind.title for key, kind in kinds.items()}
    early = [*expected_document_findings(state, user, year, titles), *issuer_findings(state, user)]
    late = [
        *duplicate_findings(state, user, kinds),
        *rereading_findings(state, user, year, kinds),
        *proposal_findings(state, user, year, titles),
        *aborted_extraction_findings(state, user),
    ]
    incoming: list[Finding] = []
    waiting = [] if site_files is None else incoming_files(site_files(), state, user)
    if waiting:
        count = len(waiting)
        text = "1 Datei im Eingang" if count == 1 else f"{count} Dateien im Eingang"
        incoming.append(
            Finding(
                INCOMING_FILES,
                Severity.NOTE,
                "eingang",
                text,
                fingerprint=fingerprint(*sorted(f.sha256 for f in waiting)),
            )
        )
    return BlockFindings(early, late, incoming)
