"""Tests: Schnappschuss bei Abgabe, Einfrieren, Vergleich, Befunde (erfundene Werte, tmp_path)."""

import datetime
import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DocumentKind, IntakeRejected, TakenIn, take_in
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import ProtocolReading
from moarcoal.modules.tax_year.anlage_n import (
    FIELDS_2025,
    N_EQUIPMENT,
    N_WORKPLACE_DAYS,
    N_WORKPLACE_DISTANCE,
    WORK_EQUIPMENT,
    WORK_GROSS_WAGES,
    WORK_INCOME_TAX,
    WORK_SOLI,
    WORK_TAX_CLASS,
    WORK_TRAVEL_FARE,
    WORK_TRAVEL_TOTAL,
    WORK_WORKDAYS,
)
from moarcoal.modules.tax_year.comparison import SNAPSHOT_DEVIATION, snapshot_on_filing
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work.entries import FirstWorkplace, UserInput, WorkEquipment
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Change,
    Document,
    Entry,
    EntryAddress,
    FrozenTime,
    FrozenValue,
    Occasion,
    Put,
    Snapshot,
    State,
    Store,
    open_store,
)
from moarcoal.values.engine import Foreign, ForeignResult, Values
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    LineItem,
    Period,
    Subject,
    TimeRef,
    Unit,
    UserInputLocator,
    ValueRef,
    ValueResult,
    Workings,
    WorkingStep,
)
from moarcoal.values.snapshots import (
    SNAPSHOT_NOT_YET,
    DeviationKind,
    compare,
    freeze,
    frozen_time,
    latest_snapshots,
)
from moarcoal.values.testing import evaluate, fixed, not_yet

FIXTURE = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
YEAR = Period.year(2025)
USER = "anna"
MODULES = [WORK, TAX_YEAR]
FIELD_KEYS = [N_WORKPLACE_DAYS, N_WORKPLACE_DISTANCE, N_EQUIPMENT]


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "protokoll.html")
    # Berichtigung: anderer Inhalt, also ein anderes Dokument
    corrected = FIXTURE.read_text(encoding="utf-8") + "\n<!-- berichtigt -->\n"
    (folder / "berichtigt.html").write_text(corrected, encoding="utf-8")
    return folder


@pytest.fixture
def store(tmp_path: Path, site: Path) -> Store:
    return open_store(tmp_path / "daten", [*WORK.kinds, *TAX_YEAR.kinds], {"Belege": site})


def values_on(state: State) -> Values:
    return Values(MODULES, state)


def take(
    store: Store, path: str = "protokoll.html", year: int = 2025, *, unique: bool = True
) -> TakenIn:
    kinds = {k.key: replace(k, unique_per_period=unique) for r in MODULES for k in r.document_kinds}
    result = take_in(
        store, kinds, USER, "Belege", path, "transfer_protocol", year, values_on=values_on
    )
    assert isinstance(result, TakenIn), result
    return result


def workplace(workdays: int = 219) -> FirstWorkplace:
    return FirstWorkplace(owner=USER, year=2025, workdays=workdays, distance_km=12)


def equipment(cents: int) -> WorkEquipment:
    day = datetime.date(2025, 5, 1)
    return WorkEquipment(
        owner=USER, year=2025, input=UserInput(amount_cents=cents, date=day, description="Stuhl")
    )


def put(store: Store, *entries: Entry) -> None:
    store.apply([Put(e) for e in entries])


def snapshots(store: Store) -> list[Snapshot]:
    return ModuleState(store.state(), TAX_YEAR, USER).snapshots()


def finding_list(store: Store) -> list[Finding]:
    return Values(MODULES, store.state()).finding_list(USER, 2025).visible


def frozen(snapshot: Snapshot, key: str) -> FrozenValue:
    return next(v for v in snapshot.values if v.ref.key == key)


# --- Aufnehmen speichert Dokument, Einlesung und Schnappschuss in einem Vorgang ---


def test_take_in_writes_document_reading_and_snapshot_in_one_vorgang(store: Store) -> None:
    put(store, workplace(), equipment(8640))
    taken = take(store)

    (snapshot,) = snapshots(store)
    assert snapshot.occasion is Occasion.FILING
    assert snapshot.module == "tax_year"
    assert snapshot.document == taken.document.address
    assert snapshot.taken_at == taken.document.taken_in_at
    assert [v.ref.key for v in snapshot.values if v.requested] == [
        f.key for f in FIELDS_2025 if f.computed
    ]
    assert frozen(snapshot, N_WORKPLACE_DAYS).amount.value == 219  # type: ignore[union-attr]
    kinds = {type(e).__name__ for e in store.state().entries.values()}
    assert {"Document", "ProtocolReading", "Snapshot"} <= kinds


def test_snapshot_survives_reopening_the_store(store: Store, tmp_path: Path, site: Path) -> None:
    put(store, workplace(), equipment(8640))
    take(store)
    (before,) = snapshots(store)

    reopened = open_store(tmp_path / "daten", [*WORK.kinds, *TAX_YEAR.kinds], {"Belege": site})

    assert snapshots(reopened) == [before]
    saved = json.loads((tmp_path / "daten" / "users" / USER / "snapshots.json").read_text())
    assert saved["schema"] == "snapshot/1"


def test_failed_vorgang_leaves_no_snapshot_and_no_document(store: Store) -> None:
    def twice(document: Document, entries: Sequence[Entry], values: Values) -> Sequence[Change]:
        changes = snapshot_on_filing(document, entries, values)
        return [*changes, *changes]  # dieselbe Adresse zweimal

    kind = replace(TAX_YEAR.document_kinds[0], after_take_in=twice)

    result = take_in(
        store,
        {kind.key: kind},
        USER,
        "Belege",
        "protokoll.html",
        kind.key,
        2025,
        values_on=values_on,
    )

    assert isinstance(result, IntakeRejected)
    assert store.state().entries == {}


def test_values_for_after_take_in_run_on_a_provisional_state_with_document_and_reading(
    store: Store,
) -> None:
    states: list[State] = []

    def capture(state: State) -> Values:
        states.append(state)
        return values_on(state)

    kind = TAX_YEAR.document_kinds[0]
    take_in(
        store, {kind.key: kind}, USER, "Belege", "protokoll.html", kind.key, 2025, values_on=capture
    )

    (state,) = states
    assert len(state.of_kind(Document)) == 1
    assert len(state.of_kind(ProtocolReading)) == 1


def test_a_kind_with_after_take_in_needs_values_on(store: Store) -> None:
    kind = TAX_YEAR.document_kinds[0]
    with pytest.raises(ValueError, match="values_on"):
        take_in(store, {kind.key: kind}, USER, "Belege", "protokoll.html", kind.key, 2025)


def test_years_without_fields_get_no_snapshot() -> None:
    document = Document(owner=USER, site="s", path="p", sha256="0" * 64)
    reading = ProtocolReading(
        owner=USER, document=document.address, year=2024, reader_version=2, lines=()
    )
    assert snapshot_on_filing(document, [reading], evaluate(MODULES)) == []


def test_a_kind_without_after_take_in_stays_as_before(store: Store) -> None:
    kind = DocumentKind("x", "x", False, lambda document, content: [])
    result = take_in(store, {"x": kind}, USER, "Belege", "protokoll.html", "x", 2025)
    assert isinstance(result, TakenIn)
    assert snapshots(store) == []


# --- Noch nicht berechenbar beim Einfrieren ---


def test_value_not_yet_computable_is_frozen_with_reason_and_gives_an_error(store: Store) -> None:
    take(store)  # nichts erfasst: Tage und km sind noch nicht berechenbar

    (snapshot,) = snapshots(store)
    days = frozen(snapshot, N_WORKPLACE_DAYS)
    assert days.outcome == "not_yet"
    assert "keine erste Tätigkeitsstätte" in days.reason
    assert days.amount is None
    errors = [f for f in finding_list(store) if f.kind == SNAPSHOT_NOT_YET]
    assert {f.severity for f in errors} == {Severity.ERROR}
    # Tage, km und die sieben Felder der Lohnsteuerbescheinigung; Arbeitsmittel sind 0 €
    assert {f.target.key for f in errors} == {  # type: ignore[union-attr]
        k for k in (f.key for f in FIELDS_2025 if f.computed) if k != N_EQUIPMENT
    }
    assert all("noch nicht berechenbar" in f.message for f in errors)


# --- Abweichung nach Änderung, Verschwinden nach Zurückändern ---


def deviations(store: Store) -> list[Finding]:
    return [f for f in finding_list(store) if f.kind == SNAPSHOT_DEVIATION]


def test_changed_input_is_reported_and_going_back_removes_it(store: Store) -> None:
    put(store, workplace(), equipment(8640))
    take(store)
    assert deviations(store) == []

    original = next(iter(store.state().of_kind(FirstWorkplace)))
    changed = original.model_copy(update={"workdays": 200})
    store.apply([Put(changed, expected=store.state().checksum(original.address))])

    (finding,) = deviations(store)
    assert finding.severity is Severity.WARNING
    assert "aufgesucht an Tagen" in finding.message
    assert "eingefroren 219 Tage, jetzt 200 Tage" in finding.message
    assert finding.href == "/steuerjahr/anlage-n/2025"

    store.apply([Put(original, expected=store.state().checksum(original.address))])
    assert deviations(store) == []


def test_added_input_deviates_on_the_amount_and_the_item(store: Store) -> None:
    put(store, workplace(), equipment(8640))
    take(store)

    put(store, equipment(1000))

    (finding,) = deviations(store)
    assert "Arbeitsmittel" in finding.message
    assert "Betrag: eingefroren 87 €, jetzt 97 €" in finding.message


def test_second_protocol_adds_a_second_snapshot_and_the_newest_is_compared(store: Store) -> None:
    put(store, workplace(), equipment(8640))
    take(store)
    put(store, equipment(1000))
    assert len(deviations(store)) == 1  # gegen die Abgabe von vorhin

    # Berichtigung mit dem neuen Stand; die Sperre je Jahr (#87) ist hier ausgeschaltet
    take(store, "berichtigt.html", unique=False)

    first, second = snapshots(store)
    assert first.taken_at <= second.taken_at
    assert frozen(first, N_EQUIPMENT).amount.value == Decimal(87)  # type: ignore[union-attr]
    assert frozen(second, N_EQUIPMENT).amount.value == Decimal(97)  # type: ignore[union-attr]
    assert deviations(store) == []


# --- Einfrieren und Vergleichen auf der Datenebene ---


PLACE = Subject(EntryAddress(kind="FirstWorkplace", id="AAAAAAAAAA"))


def with_items(*items: tuple[str, int]) -> ForeignResult:
    """Ein vorgegebener Euro-Wert mit mehreren Einzelposten, jeder eine Nutzereingabe."""

    def result(ref: ValueRef) -> ValueResult:
        built = tuple(
            LineItem(
                label,
                Amount.eur_cents(cents),
                UserInputLocator(EntryAddress(kind="WorkEquipment", id="A" * 9 + "ABCDEF"[i])),
            )
            for i, (label, cents) in enumerate(items)
        )
        total = Amount.eur_cents(sum(c for _, c in items))
        steps = tuple(WorkingStep("item", i.label, i.amount) for i in built)
        return ExposedValue(ref.key, ref.user, ref.time, ref.subject, total, built, Workings(steps))

    return result


def foreign(**given: ForeignResult) -> Foreign:
    base: dict[tuple[str, Subject | None, TimeRef], ForeignResult] = {
        (WORK_WORKDAYS, PLACE, YEAR): fixed(Amount.of(219, Unit.DAYS)),
        ("work.distance_km", PLACE, YEAR): fixed(Amount.of(12, Unit.KM)),
        (WORK_EQUIPMENT, None, YEAR): with_items(("Stuhl", 5000), ("Lampe", 3640)),
        **{
            (key, None, YEAR): not_yet("keine Lohnsteuerbescheinigung")
            for key in (
                WORK_TAX_CLASS,
                WORK_GROSS_WAGES,
                WORK_INCOME_TAX,
                WORK_SOLI,
                WORK_TRAVEL_FARE,
                WORK_TRAVEL_TOTAL,
            )
        },
    }
    base.update({(k, None, YEAR): v for k, v in given.items()})
    return base


def frozen_snapshot(given: Foreign) -> Snapshot:
    values = evaluate([TAX_YEAR], foreign=given)
    return Snapshot(
        owner=USER,
        occasion=Occasion.FILING,
        taken_at=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
        module="tax_year",
        time=freeze_time(),
        values=freeze(values, USER, FIELD_KEYS, YEAR),
    )


def freeze_time() -> FrozenTime:
    return frozen_time(YEAR)


def test_freeze_takes_the_whole_chain_as_plain_text() -> None:
    snapshot = frozen_snapshot(foreign())

    keys = [v.ref.key for v in snapshot.values]
    assert keys[:3] == FIELD_KEYS  # verlangte zuerst
    assert {"work.workdays", "work.distance_km", "work.equipment"} <= set(keys)
    assert not frozen(snapshot, "work.equipment").requested
    equipment_field = frozen(snapshot, N_EQUIPMENT)
    (item,) = equipment_field.items
    assert item.uses is not None and item.uses.key == "work.equipment"
    assert item.locator == "Wert work.equipment"
    stuhl = frozen(snapshot, "work.equipment").items[0]
    assert (stuhl.label, stuhl.backing) == ("Stuhl", "angenommen")
    assert stuhl.locator == "Nutzereingabe WorkEquipment:AAAAAAAAAA"
    assert any("übernommen" in step.text for step in equipment_field.workings)
    text = snapshot.model_dump_json()
    assert "moarcoal" not in text and "Locator" not in text


def test_compare_names_the_stage_and_the_kind_of_each_deviation() -> None:
    snapshot = frozen_snapshot(foreign())
    assert compare(snapshot, evaluate([TAX_YEAR], foreign=foreign())) == []

    now = foreign(**{WORK_EQUIPMENT: with_items(("Stuhl", 5500), ("Tisch", 1000))})
    found = compare(snapshot, evaluate([TAX_YEAR], foreign=now))

    kinds = {(d.ref.key, d.kind) for d in found}
    assert (WORK_EQUIPMENT, DeviationKind.ITEM_CHANGED) in kinds
    assert (WORK_EQUIPMENT, DeviationKind.ITEM_REMOVED) in kinds
    assert (WORK_EQUIPMENT, DeviationKind.ITEM_ADDED) in kinds
    assert (WORK_EQUIPMENT, DeviationKind.AMOUNT) in kinds
    assert (N_EQUIPMENT, DeviationKind.AMOUNT) in kinds
    removed = next(d for d in found if d.kind is DeviationKind.ITEM_REMOVED)
    assert (removed.item, removed.frozen, removed.current) == ("Lampe", "36,40 €", "")
    assert removed.text == "Einzelposten weggefallen Lampe: eingefroren 36,40 €"


def test_compare_reports_a_changed_kind_of_result() -> None:
    snapshot = frozen_snapshot(foreign())

    now = foreign(**{WORK_EQUIPMENT: not_yet("Beleg fehlt")})
    found = compare(snapshot, evaluate([TAX_YEAR], foreign=now))

    outcome = next(d for d in found if d.kind is DeviationKind.OUTCOME and d.ref.key == N_EQUIPMENT)
    assert outcome.frozen == "87,00 €"
    assert outcome.current.startswith("noch nicht berechenbar")


def test_snapshot_reads_the_same_when_the_work_module_delivers_other_items() -> None:
    snapshot = frozen_snapshot(foreign())
    before = snapshot.model_dump_json()

    other = foreign(**{WORK_EQUIPMENT: with_items(("Schreibtisch", 8640))})
    evaluate([TAX_YEAR], foreign=other)  # der aktuelle Stand ändert nichts am Eingefrorenen

    assert snapshot.model_dump_json() == before
    assert [i.label for i in frozen(snapshot, "work.equipment").items] == ["Stuhl", "Lampe"]
    assert compare(snapshot, evaluate([TAX_YEAR], foreign=other)) != []


def test_latest_snapshots_picks_the_newest_per_module_occasion_and_time() -> None:
    old = frozen_snapshot(foreign())
    new = old.model_copy(update={"id": "BBBBBBBBBB", "taken_at": old.taken_at.replace(year=2027)})
    other_year = new.model_copy(
        update={
            "id": "CCCCCCCCCC",
            "time": freeze_time().model_copy(update={"start": datetime.date(2024, 1, 1)}),
        }
    )
    assert latest_snapshots([new, old, other_year]) == [new, other_year]


# --- Seite der Anlage N und ganzer Ablauf ---


@pytest.fixture
def app(tmp_path: Path, site: Path) -> FastAPI:
    root = tmp_path / "web"
    (root / "common").mkdir(parents=True)
    (root / "common" / "sites.json").write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    return create_app(PORT, root, user=USER)


@pytest.fixture
def http(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_whole_flow_page_shows_frozen_next_to_current_and_finding_list_the_deviation(
    http: httpx.Client, app: FastAPI
) -> None:
    form = {"year": "2025", "workdays": "219", "distance_km": "12", "description": "Büro"}
    http.post("/arbeit/erste-taetigkeitsstaette", data=form, headers=ORIGIN)
    assert "Bei Abgabe" not in http.get("/steuerjahr/anlage-n/2025").text

    store: Store = app.state.store
    put(store, equipment(8640))
    taken = http.post(
        "/belege/aufnehmen",
        data={
            "sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "kind": "transfer_protocol",
            "year": "2025",
        },
        headers=ORIGIN,
    )
    assert taken.status_code == 303

    page = http.get("/steuerjahr/anlage-n/2025").text
    assert "Bei Abgabe" in page
    assert "219 Tage" in page
    assert "Abweichung zum Schnappschuss" not in http.get("/befunde?year=2025").text

    original = next(iter(store.state().of_kind(FirstWorkplace)))
    store.apply(
        [
            Put(
                original.model_copy(update={"workdays": 200}),
                expected=store.state().checksum(original.address),
            )
        ]
    )
    assert "Abweichung zum Schnappschuss" in http.get("/befunde?year=2025").text
    page = http.get("/steuerjahr/anlage-n/2025").text
    assert "Abweichung zum Schnappschuss" in page
    # Befundtext und Spalte „Bei Abgabe“ zeigen den eingefrorenen Betrag gleich
    assert "eingefroren 219 Tage" in page
    assert "<td>219 Tage</td>" in page
    assert "<td>87 €</td>" in page
    store.apply([Put(equipment(1000))])
    page = http.get("/steuerjahr/anlage-n/2025").text
    assert "eingefroren 87 €, jetzt 97 €" in page
    assert "<td>87 €</td>" in page  # dieselbe Schreibweise in der Spalte „Bei Abgabe“
