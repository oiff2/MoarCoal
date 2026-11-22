"""Befunde der Bausteine der Datenebene (Belege, Aussteller): eine Sammelfunktion für `Values`.

`Values.finding_list` kennt die Bausteine nicht einzeln; es ruft nur `block_findings`.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from moarcoal.documents import (
    DocumentKind,
    duplicate_findings,
    rereading_findings,
    unreferenced_document_findings,
)
from moarcoal.expected_documents import expected_document_findings
from moarcoal.incoming import incoming_files, missing_file_findings
from moarcoal.issuers import issuer_findings
from moarcoal.proposals import aborted_extraction_findings, proposal_findings
from moarcoal.storage import EntryKind, SiteFile, Sites, State
from moarcoal.values.findings import INCOMING_FILES, INCOMING_TARGET, Finding, Severity, fingerprint


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
    sites: Sites,
    entry_kinds: Mapping[str, EntryKind] | None = None,
) -> BlockFindings:
    """Alle Befunde der Bausteine für `user` und `year`: Erwartete Belege, Aussteller, Dokumente
    (Dubletten, Neueinlesung, fehlende Datei, Beleg ohne Verweis), Vorschläge, Abgebrochene
    Auslesungen und der Eingang (fehlende Datei und Eingang nur mit `site_files`, den Dateien
    der Ablageorte; Belege ohne Verweis nur mit `entry_kinds`)."""
    files = None if site_files is None else site_files()
    early = [*expected_document_findings(state, user, year, kinds), *issuer_findings(state, user)]
    late = [
        *duplicate_findings(state, user, kinds),
        *rereading_findings(state, user, year, kinds, sites),
        *proposal_findings(state, user, year, kinds, sites),
        *aborted_extraction_findings(state, user),
        *([] if files is None else missing_file_findings(files, state, user)),
        *(
            []
            if entry_kinds is None
            else unreferenced_document_findings(state, user, year, kinds, sites, entry_kinds)
        ),
    ]
    incoming: list[Finding] = []
    waiting = [] if files is None else incoming_files(files, state, user)
    if waiting:
        count = len(waiting)
        text = "1 Datei im Eingang" if count == 1 else f"{count} Dateien im Eingang"
        incoming.append(
            Finding(
                INCOMING_FILES,
                Severity.NOTE,
                INCOMING_TARGET,
                text,
                fingerprint=fingerprint(*sorted(f.sha256 for f in waiting)),
            )
        )
    return BlockFindings(early, late, incoming)
