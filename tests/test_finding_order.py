"""Reihenfolge der Befundliste bei gleichem Schweregrad: Bausteine (Erwartete Belege, Aussteller),
Sperrliste, Bausteine (Dubletten, Vorschläge, ...), Schnappschüsse, Module, Eingang."""

import datetime

from fastapi import APIRouter

from moarcoal.documents import DocumentKind
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Document, SiteFile, State
from moarcoal.values.engine import Values
from moarcoal.values.findings import Finding, Severity

ONCE = DocumentKind("once", "Einmalart", True, lambda d, c: [], 1, unique_per_period=True)


def document(name: str, kind: str | None) -> Document:
    return Document(
        owner="anna",
        site="Ablage",
        path=f"{name}.pdf",
        sha256=name * 64,
        document_kind=kind,
        period_start=datetime.date(2025, 1, 1) if kind else None,
        period_end=datetime.date(2025, 12, 31) if kind else None,
    )


def module_findings(state: ModuleState, values: object, year: int) -> list[Finding]:
    return [
        Finding("demo.note", Severity.NOTE, "modul", "Hinweis des Moduls"),
        Finding("demo.warning", Severity.WARNING, "modul", "Warnung des Moduls"),
    ]


def test_findings_of_equal_severity_keep_the_order_of_their_sources() -> None:
    module = ModuleRegistration(
        key="demo",
        area_name="Demo",
        nav_label="Demo",
        nav_url="/demo",
        router=APIRouter(),
        kinds=(),
        document_kinds=(ONCE,),
        findings=module_findings,
    )
    docs = [document("a", "once"), document("b", "once"), document("c", None)]
    state = State({d.address: d for d in docs}, denylist_failed=True)
    waiting = [SiteFile("Ablage", "neu.pdf", 1, "9" * 64)]
    values = Values([module], state, site_files=lambda: waiting)

    found = values.finding_list("anna", 2025).visible

    assert [(f.severity.name, f.kind) for f in found] == [
        ("WARNING", "denylist_not_written"),
        ("WARNING", "demo.warning"),
        ("NOTE", "document_without_issuer"),  # Bausteine, vor der Sperrliste
        ("NOTE", "document_without_issuer"),
        ("NOTE", "document_without_issuer"),
        ("NOTE", "document_duplicate"),  # Bausteine, nach der Sperrliste
        ("NOTE", "document_duplicate"),
        ("NOTE", "demo.note"),  # Module
        ("NOTE", "incoming_files"),  # Eingang zuletzt
    ]
