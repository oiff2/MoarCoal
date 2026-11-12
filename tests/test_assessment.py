"""Tests: Einkommensteuerbescheid auslesen und mit dem Schnappschuss der Abgabe abgleichen.

Alle Beträge sind erfunden. Die Werte von Arbeit sind fest vorgegeben; der Schnappschuss entsteht
wie im Betrieb beim Aufnehmen eines Protokolls (`snapshot_on_filing`).
"""

import datetime
import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.modules.tax_year import ASSESSMENT, ProtocolReading, registration
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_n import (
    FORMS,
    N_EQUIPMENT,
    WORK_DISTANCE_KM,
    WORK_EQUIPMENT,
    WORK_WORKDAYS,
)
from moarcoal.modules.tax_year.assessment import (
    BUSINESS_TRAVEL,
    COMMUTE_DAYS,
    COMMUTE_KM,
    GROSS_WAGES,
    MEAL_ALLOWANCE,
    TEMPLATE,
)
from moarcoal.modules.tax_year.comparison import (
    ASSESSMENT_DEVIATION,
    ASSESSMENT_NO_SNAPSHOT,
    assessment_amounts,
    current_assessment,
    snapshot_on_filing,
)
from moarcoal.modules.tax_year.fields import Direction, FormField, Rounding
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import Document, Entry, EntryAddress, Proposal, Put, State, Store
from moarcoal.storage.proposals import ProposalField
from moarcoal.values.engine import Foreign
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import Amount, Period, Subject, Unit
from moarcoal.values.testing import evaluate, fixed, not_applicable, not_yet

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)
PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))
MOMENT = datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC)


def work(workdays: int = 220, km: int = 12, cents: int = 0) -> Foreign:
    return {
        (WORK_WORKDAYS, PLACE, YEAR): fixed(Amount.of(workdays, Unit.DAYS)),
        (WORK_DISTANCE_KM, PLACE, YEAR): fixed(Amount.of(km, Unit.KM)),
        (WORK_EQUIPMENT, None, YEAR): fixed(Amount.eur_cents(cents)),
    }


def filing(foreign: Foreign, tax_year: ModuleRegistration = TAX_YEAR) -> list[Entry]:
    """Ein aufgenommenes Protokoll 2025 samt Schnappschuss der Abgabe."""
    document = Document(
        owner="anna",
        site="Belege",
        path="protokoll.html",
        sha256=f"{1:064x}",
        document_kind="transfer_protocol",
        period_start=datetime.date(2025, 1, 1),
        period_end=datetime.date(2025, 12, 31),
        taken_in_at=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
    )
    reading = ProtocolReading(
        owner="anna", document=document.address, year=2025, reader_version=2, lines=()
    )
    taken: list[Entry] = [document, reading]
    values = evaluate([tax_year], taken, foreign)
    changes = snapshot_on_filing(document, [reading], values, FORMS)
    return [*taken, *(c.entry for c in changes if isinstance(c, Put))]


def assessment(n: int = 1, year: int = 2025) -> Document:
    return Document(
        owner="anna",
        site="Belege",
        path=f"bescheid{n}.pdf",
        sha256=f"{n + 100:064x}",
        document_kind="assessment",
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
        taken_in_at=datetime.datetime(2026, 5, n, tzinfo=datetime.UTC),
    )


def proposal(
    document: Document,
    confirmed: Mapping[str, str | None],
    open_: Mapping[str, str] | None = None,
) -> Entry:
    """Ein Vorschlag mit bestätigten und offenen Feldern (Schlüssel der Auslese-Vorlage)."""
    fields = {
        key: ProposalField(value=value, location="Seite 2", confirmed=True)
        for key, value in confirmed.items()
    } | {
        key: ProposalField(value=value, location="Seite 2") for key, value in (open_ or {}).items()
    }
    return Proposal(
        owner="anna",
        document=document.address,
        template_version=1,
        fields=fields,
        raw="{}",
        created_at=MOMENT,
    )


def findings(
    items: list[Entry], foreign: Foreign | None = None, tax_year: ModuleRegistration = TAX_YEAR
) -> list[Finding]:
    values = evaluate([tax_year], items, work() if foreign is None else foreign)
    visible = values.finding_list("anna", 2025).visible
    return [f for f in visible if f.kind.startswith("tax_year.assessment_")]  # nur der Bescheid


def only(found: list[Finding], kind: str) -> Finding:
    (finding,) = [f for f in found if f.kind == kind]
    return finding


def kinds(found: list[Finding]) -> list[str]:
    return sorted(f.kind for f in found)


# --- Dokumentart und Auslese-Vorlage --------------------------------------------------------


def test_the_assessment_is_a_kind_with_period_and_an_extraction_template() -> None:
    assert ASSESSMENT in TAX_YEAR.document_kinds
    assert ASSESSMENT.has_period
    assert ASSESSMENT.extraction_template is TEMPLATE
    assert ASSESSMENT.read_in(assessment(), b"%PDF") == []


def test_every_position_a_field_names_is_in_the_template() -> None:
    template_keys = {f.key for f in TEMPLATE.fields}
    named = {key for f in FORMS[2025] for key in f.assessment}

    assert named <= template_keys
    assert {GROSS_WAGES, COMMUTE_DAYS, COMMUTE_KM, MEAL_ALLOWANCE, BUSINESS_TRAVEL} <= named


def test_positions_are_numbers_and_a_doubly_printed_label_carries_its_block() -> None:
    assert all(f.unit in {"EUR", "Tage", "km"} for f in TEMPLATE.fields)
    income = TEMPLATE.field("employment_income")
    assert income is not None and "(Einkünfte aus nichtselbständiger Arbeit)" in income.label


def test_the_fields_with_a_position_in_the_assessment() -> None:
    assert all(f.unit is not None for f in FORMS[2025] if f.assessment)
    assert [f.elster_id for f in FORMS[2025] if f.assessment] == [
        "E0200201",
        "E0200301",
        "E0200401",
        "E0203503",
        "E0203504",
        "E0205004",
        "E0205518",
    ]


# --- Abgleich: Abweichung, Gleichheit, Spanne -----------------------------------------------


def with_assessment(
    confirmed: Mapping[str, str | None], foreign: Foreign | None = None
) -> list[Finding]:
    document = assessment()
    items = [
        *filing(work() if foreign is None else foreign),
        document,
        proposal(document, confirmed),
    ]
    return findings(items)


def test_equal_assessment_gives_no_finding() -> None:
    assert with_assessment({COMMUTE_DAYS: "220", COMMUTE_KM: "12"}) == []


def test_deviation_is_a_warning_with_both_amounts_and_a_link_to_the_proposal() -> None:
    document = assessment()
    items = [*filing(work()), document, proposal(document, {COMMUTE_DAYS: "219", COMMUTE_KM: "12"})]

    found = findings(items)

    finding = only(found, ASSESSMENT_DEVIATION)
    assert kinds(found) == [ASSESSMENT_DEVIATION]
    assert finding.severity is Severity.WARNING
    assert "Laut Bescheid 219 Tage" in finding.message
    assert "bei Abgabe am 01.03.2026 220 Tage" in finding.message
    assert "aufgesucht an Tagen" in finding.message
    assert finding.href == f"/dokumente/{document.id}"


def test_the_snapshot_is_compared_not_the_current_value() -> None:
    # nach der Abgabe ändert sich Arbeit; der Bescheid gilt gegen den Stand der Abgabe
    document = assessment()
    items = [*filing(work(workdays=220)), document, proposal(document, {COMMUTE_DAYS: "220"})]

    assert ASSESSMENT_DEVIATION not in kinds(findings(items, work(workdays=200)))


def test_unconfirmed_positions_do_not_enter_the_comparison() -> None:
    document = assessment()
    items = [
        *filing(work()),
        document,
        proposal(document, {COMMUTE_KM: "12"}, open_={COMMUTE_DAYS: "1"}),
    ]

    assert findings(items) == []


def test_without_a_snapshot_there_is_a_note_instead_of_a_comparison() -> None:
    document = assessment()
    items = [document, proposal(document, {COMMUTE_DAYS: "1"})]

    found = findings(items)

    assert kinds(found) == [ASSESSMENT_NO_SNAPSHOT]
    assert found[0].severity is Severity.NOTE
    assert "keinen Schnappschuss" in found[0].message


def test_nothing_confirmed_gives_neither_comparison_nor_note() -> None:
    document = assessment()

    assert findings([document, proposal(document, {}, open_={COMMUTE_DAYS: "1"})]) == []
    assert findings([*filing(work()), document]) == []


def test_positions_without_a_field_are_not_compared() -> None:
    document = assessment()
    items = [*filing(work()), document, proposal(document, {"employee_allowance": "2.584"})]

    assert findings(items) == []


def test_a_confirmed_empty_position_counts_as_zero_and_a_printed_minus_is_ignored() -> None:
    assert with_assessment({COMMUTE_DAYS: None}, work(workdays=0)) == []
    assert with_assessment({COMMUTE_DAYS: "-220"}) == []


def test_a_field_that_does_not_apply_compares_with_zero() -> None:
    foreign = {**work(), (WORK_WORKDAYS, PLACE, YEAR): not_applicable("abgeschaltet")}

    assert with_assessment({COMMUTE_DAYS: None}, foreign) == []
    assert kinds(with_assessment({COMMUTE_DAYS: "5"}, foreign)) == [ASSESSMENT_DEVIATION]


def test_a_value_not_yet_computable_at_filing_is_not_compared() -> None:
    foreign = {**work(), (WORK_WORKDAYS, PLACE, YEAR): not_yet("keine Eingabe")}

    found = with_assessment({COMMUTE_DAYS: "5"}, foreign)

    assert ASSESSMENT_DEVIATION not in kinds(found)  # nur der Fehler der Datenebene bleibt


def printed_rounded_forms() -> dict[int, tuple[FormField, ...]]:
    """Arbeitsmittel als Feld mit Cent, das der Bescheid als Bruttoarbeitslohn gerundet druckt."""
    fields = tuple(
        replace(
            f,
            rounding=Rounding.EURO_CENTS,
            direction=None,
            printed_rounded=True,
            assessment=(GROSS_WAGES,),
        )
        if f.key == N_EQUIPMENT
        else f
        for f in FORMS[2025]
    )
    return {2025: fields}


@pytest.mark.parametrize(
    ("printed", "deviates"),
    [("86", False), ("87", False), ("85", True), ("88", True), ("86,40", True)],
)
def test_a_position_the_assessment_prints_rounded_matches_within_the_span(
    printed: str, deviates: bool
) -> None:
    forms = printed_rounded_forms()
    tax_year = registration(forms)
    document = assessment()
    items = [
        *filing(work(cents=8640), tax_year),
        document,
        proposal(document, {GROSS_WAGES: printed}),
    ]

    found = findings(items, work(cents=8640), tax_year)

    assert (ASSESSMENT_DEVIATION in kinds(found)) is deviates


def field(**given: object) -> FormField:
    base: dict[str, object] = {
        "key": "tax_year.n_demo",
        "elster_id": "E0000001",
        "form_line": "1",
        "label": "Demo",
        "unit": Unit.EUR,
        "rounding": Rounding.EURO_CENTS,
    }
    return FormField(**{**base, **given})  # type: ignore[arg-type]


def test_span_rules_of_the_field() -> None:
    cents = field()
    whole = field(rounding=Rounding.WHOLE_EUROS, direction=Direction.EXPENSE)
    rounded = field(printed_rounded=True)
    days = field(unit=Unit.DAYS, rounding=Rounding.NONE)

    assert cents.matches_assessment(Decimal("12.34"), Decimal("12.34"))
    assert not cents.matches_assessment(Decimal("12.34"), Decimal("12"))
    assert rounded.matches_assessment(Decimal("12.34"), Decimal("12"))
    assert rounded.matches_assessment(Decimal("12.34"), Decimal("13"))
    assert not rounded.matches_assessment(Decimal("12.34"), Decimal("14"))
    assert not rounded.matches_assessment(Decimal("12.34"), Decimal("12.5"))
    assert whole.matches_assessment(Decimal("12"), Decimal("12"))
    assert whole.matches_assessment(Decimal("87"), Decimal("86"))  # 86,40 eingefroren als 87
    assert whole.matches_assessment(Decimal("87"), Decimal("88"))
    assert not whole.matches_assessment(Decimal("87"), Decimal("85"))
    assert not whole.matches_assessment(Decimal("87"), Decimal("87.5"))
    assert rounded.matches_assessment(Decimal("-12.34"), Decimal("13"))  # Vorzeichen zählt nicht
    assert days.matches_assessment(Decimal("220"), Decimal("-220"))
    assert not days.matches_assessment(Decimal("220"), Decimal("221"))


def test_a_field_without_amount_has_no_position_and_a_computed_one_needs_a_unit() -> None:
    with pytest.raises(ValueError, match="Einheit"):
        field(unit=None)
    with pytest.raises(ValueError, match="ohne Betrag"):
        field(unit=None, computed=False, assessment=("gross_wages",))
    assert field(unit=None, computed=False).unit is None


# --- Welcher Bescheid, welche Beträge --------------------------------------------------------


def state_of(items: list[Entry]) -> ModuleState:
    return ModuleState(State({e.address: e for e in items}), TAX_YEAR, "anna")


def test_a_sum_field_needs_all_its_positions_confirmed_and_adds_them() -> None:
    document = assessment()
    total = next(f for f in FORMS[2025] if f.elster_id == "E0205518")

    both = state_of(
        [document, proposal(document, {MEAL_ALLOWANCE: "1.080", BUSINESS_TRAVEL: "-1.498"})]
    )
    one = state_of(
        [document, proposal(document, {MEAL_ALLOWANCE: "1.080"}, {BUSINESS_TRAVEL: "1"})]
    )

    assert assessment_amounts(both, document, FORMS[2025])[total.key] == Decimal(2578)
    assert total.key not in assessment_amounts(one, document, FORMS[2025])


def current_documents(
    state: ModuleState, year: int, fields: tuple[FormField, ...]
) -> list[Document]:
    current = current_assessment(state, year, fields)
    return [] if current is None else [current[0]]


def test_the_newest_assessment_with_confirmed_positions_counts() -> None:
    old, new, other_year = assessment(1), assessment(2), assessment(3, year=2024)
    confirmed = {COMMUTE_DAYS: "1"}
    items = [old, proposal(old, confirmed), new, proposal(new, confirmed), other_year]
    state = state_of([*items, proposal(other_year, confirmed)])
    fields = FORMS[2025]

    assert current_documents(state, 2025, fields) == [new]
    assert current_documents(state, 2024, fields) == [other_year]
    assert current_documents(state, 2023, fields) == []


def test_a_newer_assessment_without_confirmed_positions_does_not_displace_the_older() -> None:
    old, new = assessment(1), assessment(2)
    items = [
        *filing(work()),
        old,
        proposal(old, {COMMUTE_DAYS: "219"}),
        new,
        proposal(new, {}, open_={COMMUTE_DAYS: "220"}),
    ]

    assert kinds(findings(items)) == [ASSESSMENT_DEVIATION]


def test_no_snapshot_note_only_for_a_field_that_could_be_compared() -> None:
    document = assessment()
    uncomputed = [document, proposal(document, {GROSS_WAGES: "97.292"})]

    assert findings(uncomputed) == []


def test_deviation_fingerprint_follows_the_printed_and_the_frozen_amount() -> None:
    document = assessment()

    def deviation(printed: str, workdays: int = 220) -> Finding:
        items = [
            *filing(work(workdays=workdays)),
            document,
            proposal(document, {COMMUTE_DAYS: printed}),
        ]
        return only(findings(items, work(workdays=workdays)), ASSESSMENT_DEVIATION)

    base = deviation("219")

    assert deviation("219").fingerprint == base.fingerprint
    assert deviation("218").fingerprint != base.fingerprint
    assert deviation("219", workdays=221).fingerprint != base.fingerprint


# --- Seite der Anlage N und ganzer Ablauf -----------------------------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "protokoll.html")
    (folder / "bescheid.pdf").write_bytes(b"%PDF-1.4 erfundener Beispielbescheid")
    return folder


@pytest.fixture
def app(tmp_path: Path, site: Path) -> FastAPI:
    root = tmp_path / "web"
    (root / "common").mkdir(parents=True)
    (root / "common" / "sites.json").write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    return create_app(PORT, root, user="anna")


@pytest.fixture
def http(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def take(http: httpx.Client, path: Path, kind: str) -> None:
    taken = http.post(
        "/eingang/aufnehmen",
        data={
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "kind": kind,
            "year": "2025",
        },
        headers=ORIGIN,
    )
    assert taken.status_code == 303


def test_whole_flow_the_page_and_the_finding_list_show_the_assessment(
    http: httpx.Client, app: FastAPI, site: Path
) -> None:
    form = {"year": "2025", "workdays": "219", "distance_km": "12", "description": "Büro"}
    http.post("/arbeit/erste-taetigkeitsstaette", data=form, headers=ORIGIN)
    store: Store = app.state.store

    take(http, site / "bescheid.pdf", "assessment")
    document = next(d for d in store.state().of_kind(Document) if d.document_kind == "assessment")
    store.apply(
        [Put(proposal(document, {COMMUTE_DAYS: "218", COMMUTE_KM: "12", GROSS_WAGES: "97.292"}))]
    )

    page = http.get("/steuerjahr/anlage-n/2025").text
    assert "Laut Bescheid" in page
    assert "<td>218 Tage</td>" in page and "<td>97.292 €</td>" in page
    assert "wird noch nicht berechnet" in page
    note = http.get("/befunde?year=2025").text
    assert "keinen Schnappschuss" in note

    take(http, site / "protokoll.html", "transfer_protocol")

    listing = http.get("/befunde?year=2025").text
    assert "keinen Schnappschuss" not in listing
    assert "Laut Bescheid 218 Tage, bei Abgabe am" in listing
    assert f"/dokumente/{document.id}" in listing
    assert "Laut Bescheid 12 km" not in listing
