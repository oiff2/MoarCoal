"""Tests: Dienstreisen aus Screenshots auslesen (#113), nur mit Fake-Claude.

Alle Orte und Werte sind erfunden; geschrieben wird nur in `tmp_path`.
"""

import datetime
import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.extraction import Extracted, FakeExtractor, check_answer
from moarcoal.extraction_template import ExtractionTemplate, TemplateField, row_key, split_row_key
from moarcoal.modules import ModuleState
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import BusinessTrip, TripsConfirmation
from moarcoal.modules.work.trip_reading import (
    IGNORED,
    ROWS,
    STATEMENT,
    TEMPLATE,
    proposed_trips,
    take_over_changes,
)
from moarcoal.storage import Document, Proposal, ProposalField, Store, entry_checksum

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
PNG = b"\x89PNG erfundener Beispielinhalt"
SHA = hashlib.sha256(PNG).hexdigest()
USER = "anna"
YEAR = 2025
NOW = datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC)


def cell(value: object, where: str = "Zeile 1") -> dict[str, object]:
    return {"value": value, "location": where}


def trip_row(
    start: object = "2025-02-03",
    end: object = None,
    places: object = "Altstadt → Neudorf → Altstadt",
    km: object = 101,
    unsure: object = "",
) -> dict[str, dict[str, object]]:
    return {
        "start": cell(start),
        "end": cell(end),
        "places": cell(places),
        "km": cell(km),
        "unsure": cell(unsure),
    }


def raw_answer(*rows: dict[str, dict[str, object]], ignored: str = "") -> str:
    return json.dumps({IGNORED: cell(ignored, "Kopf"), ROWS: list(rows)})


def extracted(*rows: dict[str, dict[str, object]], ignored: str = "") -> Extracted:
    raw = raw_answer(*rows, ignored=ignored)
    result = check_answer(raw, TEMPLATE.json_schema())
    assert isinstance(result, Extracted)
    return result


def proposal_of(*rows: dict[str, dict[str, object]], ignored: str = "") -> Proposal:
    answer = extracted(*rows, ignored=ignored)
    fields = {
        key: ProposalField(value=answer.fields[key].value, location=answer.fields[key].location)
        for key in TEMPLATE.expected_keys(answer.fields)
    }
    document = Document(
        owner=USER,
        site="Belege",
        path="reisen.png",
        sha256=SHA,
        document_kind=STATEMENT.key,
        period_start=datetime.date(YEAR, 1, 1),
        period_end=datetime.date(YEAR, 12, 31),
        taken_in_at=NOW,
    )
    return Proposal(
        owner=USER,
        document=document.address,
        template_version=TEMPLATE.version,
        fields=fields,
        raw=answer.raw,
        created_at=NOW,
    )


def existing_trip(day: int = 3) -> BusinessTrip:
    return BusinessTrip(
        owner=USER,
        year=YEAR,
        start=datetime.date(YEAR, 2, day),
        places=("Altstadt", "Neudorf", "Altstadt"),
        distance_km=100,
    )


# --- Auslese-Vorlage mit Liste -------------------------------------------------------------------


def test_template_schema_asks_for_a_list_of_trips_and_the_ignored_columns() -> None:
    schema = TEMPLATE.json_schema()
    assert set(schema["required"]) == {IGNORED, ROWS}
    rows = schema["properties"][ROWS]
    assert rows["type"] == "array" and rows["items"]["additionalProperties"] is False
    assert set(rows["items"]["properties"]) == {"start", "end", "places", "km", "unsure"}
    hint = TEMPLATE.hint()
    assert ROWS in hint and "Tagespauschale" in hint and "Kilometer" in hint


def test_list_cells_become_one_field_each_in_row_order() -> None:
    answer = extracted(trip_row(km=101), trip_row(start="2025-03-04", km=None))
    assert list(answer.fields) == [
        IGNORED,
        *(row_key(ROWS, 1, c) for c in ("start", "end", "places", "km", "unsure")),
        *(row_key(ROWS, 2, c) for c in ("start", "end", "places", "km", "unsure")),
    ]
    assert answer.fields[row_key(ROWS, 2, "km")].value is None
    assert split_row_key("trips.2.km") == ("trips", 2, "km")
    assert split_row_key("km") is None


def test_a_list_that_does_not_fit_the_schema_is_an_invalid_answer() -> None:
    wrong = json.dumps({IGNORED: cell(""), ROWS: [{"start": cell("2025-02-03")}]})
    assert not isinstance(check_answer(wrong, TEMPLATE.json_schema()), Extracted)
    flat = json.dumps({IGNORED: cell(""), ROWS: cell("x")})
    assert not isinstance(check_answer(flat, TEMPLATE.json_schema()), Extracted)


def test_cells_are_resolved_to_their_column_with_the_row_number() -> None:
    spec = TEMPLATE.field("trips.3.km")
    assert spec is not None and spec.unit == "km" and spec.label == "km (Reise 3)"
    assert TEMPLATE.field("trips.3.nope") is None and TEMPLATE.field("other.3.km") is None


def test_template_rejects_ambiguous_keys() -> None:
    field = TemplateField("a", "A")
    with pytest.raises(ValueError):
        ExtractionTemplate(1, (field,), "a", (field,))  # Schlüssel der Liste doppelt
    with pytest.raises(ValueError):
        ExtractionTemplate(1, (field,), "rows", ())  # Liste ohne Spalten
    with pytest.raises(ValueError):
        ExtractionTemplate(1, (TemplateField("a.b", "A"),))  # Punkt im Schlüssel


# --- Fachkern ------------------------------------------------------------------------------------


def test_markers_missing_km_uncertain_duplicate_and_out_of_year() -> None:
    proposal = proposal_of(
        trip_row(),  # 1: in Ordnung
        trip_row(start="2025-02-10", km=None),  # 2: km fehlen
        trip_row(start="2025-02-11", unsure="km, places"),  # 3: unsicher
        trip_row(start="2025-02-03"),  # 4: Dublette zur gespeicherten Reise
        trip_row(start="2024-12-20"),  # 5: außerhalb des Jahres
        trip_row(start="2025-03-01", places="Altstadt"),  # 6: ein Ort
    )
    found = {t.number: t for t in proposed_trips(proposal, YEAR, [existing_trip(3)])}
    ok, no_km, unsure, dup, other_year, one_place = (found[n] for n in range(1, 7))
    assert ok.takeable and ok.duplicate  # 1 teilt das Startdatum 03.02. mit der gespeicherten
    assert no_km.errors["km"] == "km fehlen." and not no_km.takeable
    assert unsure.uncertain == {"km", "places"} and unsure.takeable and not unsure.preselected
    assert dup.duplicate and not dup.preselected and dup.takeable
    assert other_year.out_of_year and other_year.year == 2024 and not other_year.preselected
    assert other_year.takeable
    assert "orte" in one_place.errors and not one_place.takeable


def test_a_plain_trip_is_preselected() -> None:
    (only,) = proposed_trips(proposal_of(trip_row()), YEAR, [])
    assert only.preselected and only.row.km == "101"


@pytest.mark.parametrize(
    "km, expected",
    [(101, "101"), ("1.234", "1234"), (None, ""), ("12,5", "12,5"), ("viel", "viel")],
)
def test_km_must_be_a_whole_number(km: object, expected: str) -> None:
    (only,) = proposed_trips(proposal_of(trip_row(km=km)), YEAR, [])
    assert only.row.km == expected
    assert only.takeable is (expected.replace(",", "").isdigit() and "," not in expected)


def test_take_over_writes_trips_and_confirms_exactly_their_fields() -> None:
    proposal = proposal_of(trip_row(), trip_row(start="2025-03-04", km=None), ignored="Spesen")
    changes, problems = take_over_changes(proposal, YEAR, {1}, USER, [], entry_checksum(proposal))
    assert problems == {}
    *trips, changed = changes
    (trip,) = (c.entry for c in trips)
    assert isinstance(trip, BusinessTrip) and trip.distance_km == 101 and trip.year == YEAR
    assert trip.places == ("Altstadt", "Neudorf", "Altstadt")
    proposal_after = changed.entry
    assert isinstance(proposal_after, Proposal)
    assert changed.expected == entry_checksum(proposal)
    assert proposal_after.open_keys == [
        row_key(ROWS, 2, c) for c in ("start", "end", "places", "km", "unsure")
    ]


def test_take_over_uses_corrections_and_refuses_everything_if_one_row_cannot_be_taken() -> None:
    proposal = proposal_of(trip_row(km=None), trip_row(start="2025-03-04"))
    key = row_key(ROWS, 1, "km")
    corrected = proposal.model_copy(
        update={"fields": {**proposal.fields, key: proposal.fields[key].model_copy(
            update={"correction": "77"}
        )}}
    )  # fmt: skip
    changes, problems = take_over_changes(corrected, YEAR, {1}, USER, [], "x")
    assert problems == {} and changes[0].entry.distance_km == 77  # type: ignore[attr-defined]
    changes, problems = take_over_changes(proposal, YEAR, {1, 2}, USER, [], "x")
    assert changes == [] and problems == {1: "km fehlen."}
    assert take_over_changes(proposal, YEAR, set(), USER, [], "x") == ([], {})


def test_a_trip_taken_over_before_cannot_be_taken_again() -> None:
    proposal = proposal_of(trip_row())
    changes, _ = take_over_changes(proposal, YEAR, {1}, USER, [], "x")
    done = changes[-1].entry
    assert isinstance(done, Proposal)
    (item,) = proposed_trips(done, YEAR, [])
    assert item.taken and not item.takeable
    again, problems = take_over_changes(done, YEAR, {1}, USER, [], "x")
    assert again == [] and 1 in problems


# --- Seite ---------------------------------------------------------------------------------------


class Setup:
    def __init__(self, root: Path, fake: FakeExtractor) -> None:
        site = root / "ablage"
        site.mkdir(parents=True)
        (site / "reisen.png").write_bytes(PNG)
        sites = root / "data" / "common" / "sites.json"
        sites.parent.mkdir(parents=True)
        sites.write_text(
            json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
        )
        self.root = root / "data"
        self.fake = fake
        self.app = make_app(PORT, self.root, [WORK], user=USER, extractor=fake)
        self.client: httpx.Client = TestClient(
            self.app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False
        )

    @property
    def store(self) -> Store:
        return self.app.state.store

    def post(self, url: str, **data: str) -> httpx.Response:
        return self.client.post(url, data=data, headers=ORIGIN)

    def read_out(self) -> Document:
        taken = self.post("/belege/aufnehmen", sha256=SHA, kind=STATEMENT.key, year=str(YEAR))
        assert taken.status_code == 303
        document = self.store.state().of_kind(Document)[0]
        assert self.post(f"/dokumente/{document.id}/auslesen").status_code == 303
        return document

    def proposal(self) -> Proposal:
        return self.store.state().of_kind(Proposal)[0]

    def trips(self) -> list[BusinessTrip]:
        return sorted(self.store.state().of_kind(BusinessTrip), key=lambda t: t.start)

    def page(self) -> str:
        response = self.client.get(f"/arbeit/dienstreisen/{YEAR}")
        assert response.status_code == 200
        return response.text

    def take_over(self, *numbers: int, checksum: str | None = None) -> httpx.Response:
        proposal = self.proposal()
        data = {f"nimm-{n}": "ja" for n in numbers}
        data["pruefsumme"] = checksum if checksum is not None else entry_checksum(proposal)
        return self.post(f"/arbeit/dienstreisen/{YEAR}/vorschlag/{proposal.id}/uebernehmen", **data)


def make(tmp_path: Path, *rows: dict[str, dict[str, object]], ignored: str = "") -> Setup:
    return Setup(tmp_path, FakeExtractor([extracted(*rows, ignored=ignored)]))


def test_the_reading_goes_through_the_one_extractor_with_the_templates_schema(
    tmp_path: Path,
) -> None:
    setup = make(tmp_path, trip_row())
    setup.read_out()
    ((content, media_type, schema, hint),) = setup.fake.calls
    assert content == PNG and media_type == "image/png"
    assert schema == TEMPLATE.json_schema() and hint == TEMPLATE.hint()
    assert ROWS in schema["properties"]


def test_the_page_shows_the_proposal_table_with_markers_and_get_never_writes(
    tmp_path: Path,
) -> None:
    setup = make(
        tmp_path,
        trip_row(),
        trip_row(start="2025-02-10", km=None),
        trip_row(start="2025-02-11", unsure="km"),
        trip_row(start="2024-12-20"),
        ignored="Verpflegung, Übernachtung",
    )
    assert "Noch nicht ausgelesen" not in setup.page()
    setup.read_out()
    before = {p: p.read_bytes() for p in setup.root.rglob("*.json")}
    page = setup.page()
    assert {p: p.read_bytes() for p in setup.root.rglob("*.json")} == before
    assert "Nicht übernommen, das rechnet der Arbeitgeber ab: Verpflegung, Übernachtung." in page
    assert "km fehlen." in page and "unsicher gelesen: km" in page
    assert "liegt nicht in 2025, würde für 2024 gelten" in page
    boxes = re.findall(r'<input type="checkbox" name="nimm-(\d)"([^>]*)>', page)
    state = {n: ("checked" in rest, "disabled" in rest) for n, rest in boxes}
    assert state == {
        "1": (True, False),  # vorgewählt
        "2": (False, True),  # ohne km nicht übernehmbar
        "3": (False, False),  # unsicher: nicht vorgewählt
        "4": (False, False),  # außerhalb des Jahrs: nicht vorgewählt
    }
    assert "Reiseaufstellung (Screenshot)" in setup.client.get("/belege?datei=" + SHA).text


def test_a_document_that_is_not_read_out_yet_points_to_the_documents_tab(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row())
    setup.post("/belege/aufnehmen", sha256=SHA, kind=STATEMENT.key, year=str(YEAR))
    page = setup.page()
    assert "Noch nicht ausgelesen" in page and "/belege/dokumente?dokument=" in page
    assert setup.fake.calls == []  # ausgelesen wird nur auf Wunsch


def test_take_over_writes_the_trips_and_confirms_the_fields_in_one_step(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(), trip_row(start="2025-02-10", km=None))
    setup.read_out()
    setup.post(f"/arbeit/dienstreisen/{YEAR}/vollstaendig", stand=_stand(setup))
    assert setup.store.state().of_kind(TripsConfirmation)
    response = setup.take_over(1)
    assert response.status_code == 303
    (trip,) = setup.trips()
    assert trip.distance_km == 101 and trip.start == datetime.date(2025, 2, 3)
    assert trip.places == ("Altstadt", "Neudorf", "Altstadt") and trip.year == YEAR
    assert setup.proposal().open_keys == [
        row_key(ROWS, 2, c) for c in ("start", "end", "places", "km", "unsure")
    ]
    page = setup.page()
    assert "übernommen" in page and "Noch nicht als vollständig bestätigt" in page
    assert "Altstadt → Neudorf → Altstadt" in page


def _stand(setup: Setup) -> str:
    return re.search(r'name="stand" value="([^"]*)"', setup.page()).group(1)  # type: ignore[union-attr]


def test_a_trip_without_km_is_never_taken_over(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(km=None), trip_row(start="2025-02-10"))
    setup.read_out()
    response = setup.take_over(1, 2)
    assert response.status_code == 422 and "km fehlen." in response.text
    assert setup.trips() == [] and len(setup.proposal().open_keys) == 11  # nichts übernommen
    assert setup.proposal().fields[IGNORED].confirmed is False


def test_nothing_chosen_takes_nothing(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row())
    setup.read_out()
    response = setup.take_over()
    assert response.status_code == 422 and "Keine Reise gewählt." in response.text
    assert setup.trips() == []


def test_an_out_of_year_trip_is_taken_over_for_the_year_of_its_start(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(start="2024-12-20"))
    setup.read_out()
    assert setup.take_over(1).status_code == 303
    (trip,) = setup.trips()
    assert trip.year == 2024


def test_a_stale_page_is_rejected_by_the_write_path(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(), trip_row(start="2025-02-10"))
    setup.read_out()
    stale = entry_checksum(setup.proposal())
    assert setup.take_over(1).status_code == 303
    again = setup.take_over(2, checksum=stale)
    assert again.status_code == 409 and len(setup.trips()) == 1


def test_delete_removes_the_proposal_and_keeps_the_trips(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(), trip_row(start="2025-02-10"))
    document = setup.read_out()
    setup.take_over(1)
    proposal = setup.proposal()
    response = setup.post(
        f"/arbeit/dienstreisen/{YEAR}/vorschlag/{proposal.id}/loeschen",
        pruefsumme=entry_checksum(proposal),
    )
    assert response.status_code == 303
    assert setup.store.state().of_kind(Proposal) == [] and len(setup.trips()) == 1
    assert "Noch nicht ausgelesen" in setup.page() and document.id in setup.page()


def test_unknown_or_foreign_proposals_are_404_and_other_origins_are_refused(
    tmp_path: Path,
) -> None:
    setup = make(tmp_path, trip_row())
    setup.read_out()
    url = f"/arbeit/dienstreisen/{YEAR}/vorschlag/{setup.proposal().id}/uebernehmen"
    assert setup.post(f"/arbeit/dienstreisen/{YEAR}/vorschlag/NOPE/uebernehmen").status_code == 404
    assert setup.post(f"/arbeit/dienstreisen/{YEAR + 1}/vorschlag/x/uebernehmen").status_code == 404
    assert setup.client.post(url, data={"nimm-1": "ja"}).status_code in (400, 403)
    assert setup.trips() == []


def test_text_from_claude_is_escaped(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row(places="<script>x</script> → Neudorf"), ignored="<b>Spesen</b>")
    setup.read_out()
    page = setup.page()
    assert "<script>x</script>" not in page and "<b>Spesen</b>" not in page
    assert "&lt;script&gt;" in page


def test_the_generic_document_tab_labels_the_trip_cells(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row())
    document = setup.read_out()
    tab = setup.client.get(f"/belege/dokumente?dokument={document.id}").text
    assert "km (Reise 1)" in tab and "Start (Reise 1)" in tab


def test_confirmed_fields_are_readable_through_the_module_state(tmp_path: Path) -> None:
    setup = make(tmp_path, trip_row())
    document = setup.read_out()
    setup.take_over(1)
    confirmed = ModuleState(setup.store.state(), WORK, USER).confirmed_fields(document)
    assert str(confirmed[row_key(ROWS, 1, "km")][0]) == "101"
