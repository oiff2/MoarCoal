"""Auslesen als Vorschlag: Vorlage, Auslesen, Bestätigen, Befund, Seite, Fundstelle (nur Fake)."""

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from moarcoal.app import create_app
from moarcoal.documents import DocumentKind
from moarcoal.extraction import (
    Extracted,
    ExtractedField,
    ExtractionFailed,
    FailureReason,
    FakeExtractor,
)
from moarcoal.extraction_template import ExtractionTemplate, TemplateField
from moarcoal.links import document_url
from moarcoal.proposals import UNCONFIRMED
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import AbortedExtraction, Change, Document, Proposal, Rejected, Store
from moarcoal.values.model import Backing, DocumentLocator, Source

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
CONTENT = b"%PDF-1.4 erfundener Beispielinhalt"
SHA = hashlib.sha256(CONTENT).hexdigest()
TEMPLATE = ExtractionTemplate(
    3,
    (
        TemplateField("tax", "Steuer", "EUR", "Betrag der festgesetzten Steuer"),
        TemplateField("date", "Datum"),
    ),
)
KIND = DocumentKind(
    key="notice",
    title="Beispielbescheid",
    has_period=True,
    read_in=lambda d, c: [],
    extraction_template=TEMPLATE,
)
PLAIN = DocumentKind(key="plain", title="Ohne Vorlage", has_period=False, read_in=lambda d, c: [])
REGISTRATION = ModuleRegistration(
    key="beispiel",
    area_name="Beispiel",
    nav_label="Beispiel",
    nav_url="/beispiel",
    router=APIRouter(),
    kinds=(),
    document_kinds=(KIND, PLAIN),
)


def answer(tax: str = "1.234,00", date: str = "01.02.2026") -> Extracted:
    fields = {
        "tax": ExtractedField(value=tax, location="Seite 1, Zeile 4"),
        "date": ExtractedField(value=date, location="Seite 1, Kopf"),
    }
    return Extracted(fields, json.dumps({k: v.model_dump() for k, v in fields.items()}))


class Setup:
    def __init__(self, root: Path, site: Path, fake: FakeExtractor) -> None:
        self.fake = fake
        sites = root / "common" / "sites.json"
        sites.parent.mkdir(parents=True, exist_ok=True)
        sites.write_text(
            json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
        )
        self.app = create_app(PORT, root, [REGISTRATION], user="anna", extractor=fake)
        self.client: httpx.Client = TestClient(
            self.app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False
        )

    @property
    def store(self) -> Store:
        return self.app.state.store

    def take_in(self, kind: str = "notice") -> str:
        """Nimmt auf; gibt bei Art mit Vorlage die Routen des Dokuments (`/dokumente/{id}`) zurück,
        sonst den Ort der Weiterleitung."""
        data = {"sha256": SHA, "kind": kind, "year": "2025"}
        response = self.client.post("/belege/aufnehmen", data=data, headers=ORIGIN)
        assert response.status_code == 303
        location = response.headers["location"]
        if location.startswith("/belege/dokumente?dokument="):
            return f"/dokumente/{location.removeprefix('/belege/dokumente?dokument=')}"
        return location

    def post(self, url: str, **data: str) -> httpx.Response:
        return self.client.post(url, data=data, headers=ORIGIN)

    def document(self) -> Document:
        return self.store.state().of_kind(Document)[0]

    def proposal(self) -> Proposal:
        return self.store.state().of_kind(Proposal)[0]

    def module_state(self) -> ModuleState:
        return ModuleState(self.store.state(), REGISTRATION, "anna")


def make(tmp_path: Path, *answers: Extracted | ExtractionFailed) -> Setup:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "bescheid.pdf").write_bytes(CONTENT)
    return Setup(tmp_path / "daten", site, FakeExtractor(list(answers)))


def findings(setup: Setup, year: int = 2025) -> list[Any]:
    from moarcoal.values.engine import Values

    values = Values([REGISTRATION], setup.store.state())
    return [f for f in values.finding_list("anna", year).visible if f.kind == UNCONFIRMED]


# --- Vorlage -----------------------------------------------------------------------------------


def test_template_builds_the_schema_and_the_hint() -> None:
    schema = TEMPLATE.json_schema()
    assert list(schema["properties"]) == ["tax", "date"]
    assert schema["required"] == ["tax", "date"]
    assert "Einheit: EUR" in schema["properties"]["tax"]["description"]
    assert "Betrag der festgesetzten Steuer" in TEMPLATE.hint()


def test_template_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError):
        ExtractionTemplate(1, (TemplateField("a", "A"), TemplateField("a", "B")))


# --- Auslesen ----------------------------------------------------------------------------------


def test_take_in_leads_to_the_documents_tab_and_get_writes_nothing(tmp_path: Path) -> None:
    setup = make(tmp_path)
    data = {"sha256": SHA, "kind": "notice", "year": "2025"}
    response = setup.client.post("/belege/aufnehmen", data=data, headers=ORIGIN)
    tab = f"/belege/dokumente?dokument={setup.document().id}"
    assert response.headers["location"] == tab
    before = setup.store.state().entries
    page = setup.client.get(tab)
    assert page.status_code == 200
    assert "Auslesen" in page.text
    assert (
        f"/dokumente/{setup.document().id}/auslesen" in page.text
    )  # Kopf rechts, Vorschau darunter
    assert "Dokument</a>" not in page.text
    assert setup.store.state().entries == before
    assert setup.fake.calls == []


def test_extract_creates_a_proposal_with_the_template_version(tmp_path: Path) -> None:
    setup = make(tmp_path, answer())
    location = setup.take_in()
    response = setup.post(f"{location}/auslesen")
    assert response.status_code == 303
    proposal = setup.proposal()
    assert proposal.document == setup.document().address
    assert proposal.template_version == 3
    assert proposal.fields["tax"].value == "1.234,00"
    assert proposal.fields["tax"].location == "Seite 1, Zeile 4"
    assert not any(f.confirmed for f in proposal.fields.values())
    assert "tax" in proposal.raw
    content, media_type, schema, hint = setup.fake.calls[0]
    assert (content, media_type) == (CONTENT, "application/pdf")
    assert schema == TEMPLATE.json_schema()
    assert hint == TEMPLATE.hint()


def test_failed_extraction_creates_no_proposal_and_shows_the_message(tmp_path: Path) -> None:
    failed = ExtractionFailed(FailureReason.TIMEOUT, "Claude hat nicht rechtzeitig geantwortet.")
    setup = make(tmp_path, failed)
    location = setup.take_in()
    response = setup.post(f"{location}/auslesen")
    assert response.status_code == 409
    assert "Claude hat nicht rechtzeitig geantwortet." in response.text
    assert setup.store.state().of_kind(Proposal) == []


def test_extract_needs_origin(tmp_path: Path) -> None:
    setup = make(tmp_path, answer())
    location = setup.take_in()
    response = setup.client.post(f"{location}/auslesen")
    assert response.status_code == 403
    assert setup.fake.calls == []


def test_re_extraction_creates_a_new_proposal_next_to_the_old_one(tmp_path: Path) -> None:
    setup = make(tmp_path, answer(), answer(tax="9.999,00"))
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    setup.post(f"{location}/bestaetigen", all="1")
    assert "Neu auslesen" in setup.client.get(document_url(setup.document().id)).text
    assert setup.post(f"{location}/auslesen").status_code == 303
    proposals = setup.store.state().of_kind(Proposal)
    assert len(proposals) == 2
    newest = max(proposals, key=lambda p: (p.created_at, p.id))
    assert newest.fields["tax"].value == "9.999,00"
    assert not any(f.confirmed for f in newest.fields.values())  # nichts übernommen
    page = setup.client.get(document_url(setup.document().id)).text
    assert "9.999,00" in page and "1.234,00" not in page
    assert setup.module_state().confirmed_fields(setup.document()) == {}
    [finding] = findings(setup)  # nur der neueste Vorschlag zählt
    assert "2 von 2" in finding.message
    setup.post(f"{location}/bestaetigen", field="tax")
    content, _ = setup.module_state().confirmed_fields(setup.document())["tax"]
    assert content == Decimal("9999.00")


def test_failed_re_extraction_keeps_the_current_proposal(tmp_path: Path) -> None:
    failed = ExtractionFailed(FailureReason.TIMEOUT, "Zeitüberschreitung.")
    setup = make(tmp_path, answer(), failed)
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    setup.post(f"{location}/bestaetigen", all="1")
    assert setup.post(f"{location}/auslesen").status_code == 409
    assert len(setup.store.state().of_kind(Proposal)) == 1
    content, _ = setup.module_state().confirmed_fields(setup.document())["tax"]
    assert content == Decimal("1234.00")


def test_kind_without_template_is_not_extracted(tmp_path: Path) -> None:
    setup = make(tmp_path, answer())
    location = setup.take_in("plain")
    assert location == "/belege"
    document_path = f"/dokumente/{setup.document().id}"
    assert "nicht ausgelesen" in setup.client.get(document_url(setup.document().id)).text
    assert setup.post(f"{document_path}/auslesen").status_code == 409
    assert setup.fake.calls == []


def test_unknown_document_is_404(tmp_path: Path) -> None:
    setup = make(tmp_path)
    assert setup.post("/dokumente/AAAAAAAAAA/auslesen").status_code == 404
    assert setup.post("/dokumente/kaputt/bestaetigen", all="1").status_code == 404
    assert setup.client.get("/dokumente/kaputt/datei").status_code == 404


# --- Bestätigen --------------------------------------------------------------------------------


def extracted(tmp_path: Path, *answers: Extracted) -> tuple[Setup, str]:
    setup = make(tmp_path, *(answers or (answer(),)))
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    return setup, location


def test_confirm_one_field_saves_it(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    response = setup.post(f"{location}/bestaetigen", field="tax", correction="")
    assert response.status_code == 303
    fields = setup.proposal().fields
    assert fields["tax"].confirmed and fields["tax"].correction is None
    assert not fields["date"].confirmed


def test_correction_keeps_the_extracted_content_beside_it(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    setup.post(f"{location}/bestaetigen", field="tax", correction="1.243,00")
    field = setup.proposal().fields["tax"]
    assert field.confirmed
    assert field.value == "1.234,00"
    assert field.correction == "1.243,00"
    page = setup.client.get(document_url(setup.document().id)).text
    assert "1.234,00" in page and "1.243,00" in page


def test_confirm_all(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    setup.post(f"{location}/bestaetigen", field="tax", correction="1.243,00")
    response = setup.post(f"{location}/bestaetigen", all="1")
    assert response.status_code == 303
    fields = setup.proposal().fields
    assert all(f.confirmed for f in fields.values())
    assert fields["tax"].correction == "1.243,00"  # schon Bestätigtes bleibt


def test_confirm_needs_origin_and_unknown_field_is_refused(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    assert setup.client.post(f"{location}/bestaetigen", data={"all": "1"}).status_code == 403
    assert setup.post(f"{location}/bestaetigen", field="gibtsnicht").status_code == 409
    assert not any(f.confirmed for f in setup.proposal().fields.values())


def test_confirm_without_proposal_is_refused(tmp_path: Path) -> None:
    setup = make(tmp_path)
    location = setup.take_in()
    assert setup.post(f"{location}/bestaetigen", all="1").status_code == 409


def test_content_from_claude_is_escaped(tmp_path: Path) -> None:
    evil = "<script>alert(1)</script>"
    fields = {
        "tax": ExtractedField(value=evil, location=f"{evil} Seite"),
        "date": ExtractedField(value="x", location="y"),
    }
    setup, location = extracted(tmp_path, Extracted(fields, evil))
    setup.post(f"{location}/bestaetigen", field="tax", correction=evil)
    page = setup.client.get(document_url(setup.document().id)).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)" not in setup.client.get("/befunde?year=2025").text


# --- Befund ------------------------------------------------------------------------------------


def test_open_fields_give_a_note_with_a_link_and_confirming_all_removes_it(
    tmp_path: Path,
) -> None:
    setup, location = extracted(tmp_path)
    [finding] = findings(setup)
    assert finding.severity.value == "Hinweis"
    assert finding.href == document_url(setup.document().id)
    assert "2 von 2" in finding.message
    page = setup.client.get("/befunde?year=2025").text
    assert f'href="{document_url(setup.document().id)}"' in page
    setup.post(f"{location}/bestaetigen", field="tax")
    [partly] = findings(setup)
    assert "1 von 2" in partly.message
    assert partly.fingerprint != finding.fingerprint
    setup.post(f"{location}/bestaetigen", all="1")
    assert findings(setup) == []


def test_finding_belongs_to_the_year_of_the_document(tmp_path: Path) -> None:
    setup, _ = extracted(tmp_path)
    assert findings(setup, 2024) == []


# --- Fundstelle und bestätigte Felder ----------------------------------------------------------


def test_only_confirmed_fields_are_given_with_a_locator(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    document = setup.document()
    assert setup.module_state().confirmed_fields(document) == {}
    setup.post(f"{location}/bestaetigen", field="tax")
    fields = setup.module_state().confirmed_fields(document)
    assert list(fields) == ["tax"]
    content, locator = fields["tax"]
    assert content == Decimal("1234.00")
    assert locator == DocumentLocator(
        document.address, Source.DOCUMENT_EXTRACTION, "tax", "Seite 1, Zeile 4"
    )
    assert locator.backing is Backing.PROVEN
    assert locator.entry_address == document.address


def test_field_with_unit_comes_as_a_number_whether_extracted_or_corrected(
    tmp_path: Path,
) -> None:
    number = Extracted(
        {
            "tax": ExtractedField(value=1234.5, location="Seite 1"),
            "date": ExtractedField(value="01.02.2026", location="Kopf"),
        },
        "{}",
    )
    setup, location = extracted(tmp_path, number)
    setup.post(f"{location}/bestaetigen", all="1")
    fields = setup.module_state().confirmed_fields(setup.document())
    assert fields["tax"][0] == Decimal("1234.5")
    assert fields["date"][0] == "01.02.2026"  # ohne Einheit bleibt der Text
    setup.post(f"{location}/bestaetigen", field="tax", correction="1.300,10 €")
    assert setup.module_state().confirmed_fields(setup.document())["tax"][0] == Decimal("1300.10")


def test_correction_of_a_field_with_unit_must_be_a_number(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    response = setup.post(f"{location}/bestaetigen", field="tax", correction="zwölf")
    assert response.status_code == 409
    assert "Steuer: Zahl erwartet" in response.text
    assert not setup.proposal().fields["tax"].confirmed


def test_extracted_text_that_is_no_number_cannot_be_confirmed_without_correction(
    tmp_path: Path,
) -> None:
    setup, location = extracted(tmp_path, answer(tax="siehe Anlage"))
    assert setup.post(f"{location}/bestaetigen", all="1").status_code == 409
    assert not any(f.confirmed for f in setup.proposal().fields.values())
    setup.post(f"{location}/bestaetigen", field="tax", correction="")
    assert not setup.proposal().fields["tax"].confirmed
    setup.post(f"{location}/bestaetigen", field="tax", correction="12,00")
    assert setup.module_state().confirmed_fields(setup.document())["tax"][0] == Decimal("12.00")


def test_corrected_field_gives_the_corrected_content_with_backing_proven(tmp_path: Path) -> None:
    setup, location = extracted(tmp_path)
    setup.post(f"{location}/bestaetigen", field="tax", correction="1.243,00")
    content, locator = setup.module_state().confirmed_fields(setup.document())["tax"]
    assert content == Decimal("1243.00")
    assert locator.source is Source.DOCUMENT_EXTRACTION
    assert locator.place == "Seite 1, Zeile 4"
    assert locator.backing is Backing.PROVEN


def test_confirmed_fields_come_from_the_newest_proposal_and_only_for_the_owner(
    tmp_path: Path,
) -> None:
    setup, location = extracted(tmp_path)
    setup.post(f"{location}/bestaetigen", all="1")
    document = setup.document()
    older = setup.proposal()
    newer = older.model_copy(
        update={
            "id": "AAAAAAAAAA",
            "created_at": older.created_at.replace(year=older.created_at.year + 1),
            "fields": {
                k: f.model_copy(update={"confirmed": False}) for k, f in older.fields.items()
            },
        }
    )
    from moarcoal.storage import Put

    setup.store.apply([Put(newer)])
    assert setup.module_state().confirmed_fields(document) == {}
    stranger = ModuleState(setup.store.state(), REGISTRATION, "berta")
    assert stranger.confirmed_fields(document) == {}


def test_document_locator_label_names_the_source_and_the_place() -> None:
    from moarcoal.storage import EntryAddress

    locator = DocumentLocator(
        EntryAddress(kind="Document", id="AAAAAAAAAA"), Source.DOCUMENT_EXTRACTION, "k", "Seite 2"
    )
    assert locator.label == "Dokumentauslesung: Seite 2"


# --- Abgebrochene Auslesung --------------------------------------------------------------------

TOOLS = ExtractionFailed(FailureReason.TOOLS_REPORTED, "Claude meldet Werkzeuge.")


def aborted_findings(setup: Setup) -> list[Any]:
    from moarcoal.values.engine import Values

    values = Values([REGISTRATION], setup.store.state())
    return [f for f in values.finding_list("anna", 2025).visible if f.kind == "claude_tools"]


def test_tools_abort_is_recorded_with_an_error_finding_linking_the_document(
    tmp_path: Path,
) -> None:
    setup = make(tmp_path, TOOLS)
    location = setup.take_in()
    assert setup.post(f"{location}/auslesen").status_code == 409
    [aborted] = setup.store.state().of_kind(AbortedExtraction)
    assert aborted.document == setup.document().address
    assert aborted.reason == "tools_reported"
    assert setup.store.state().of_kind(Proposal) == []
    [finding] = aborted_findings(setup)
    assert finding.severity.value == "Fehler"
    assert finding.target == setup.document().address
    assert finding.href == document_url(setup.document().id)
    assert (
        f'href="{document_url(setup.document().id)}"' in setup.client.get("/befunde?year=2025").text
    )
    before = setup.store.state().entries
    setup.client.get(document_url(setup.document().id))
    setup.client.get("/befunde?year=2025")
    assert setup.store.state().entries == before


def test_later_success_removes_the_entry_and_the_finding(tmp_path: Path) -> None:
    setup = make(tmp_path, TOOLS, answer())
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    assert setup.post(f"{location}/auslesen").status_code == 303
    assert setup.store.state().of_kind(AbortedExtraction) == []
    assert len(setup.store.state().of_kind(Proposal)) == 1
    assert aborted_findings(setup) == []


def test_other_failures_are_not_recorded(tmp_path: Path) -> None:
    invalid = ExtractionFailed(FailureReason.INVALID_ANSWER, "ungültig")
    setup = make(tmp_path, invalid)
    setup.post(f"{setup.take_in()}/auslesen")
    assert setup.store.state().of_kind(AbortedExtraction) == []
    assert aborted_findings(setup) == []


def test_other_failure_keeps_an_earlier_abort(tmp_path: Path) -> None:
    timeout = ExtractionFailed(FailureReason.TIMEOUT, "zu spät")
    setup = make(tmp_path, TOOLS, timeout)
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    setup.post(f"{location}/auslesen")
    assert len(setup.store.state().of_kind(AbortedExtraction)) == 1


def test_second_abort_replaces_the_entry_and_brings_back_a_dismissed_finding(
    tmp_path: Path,
) -> None:
    setup = make(tmp_path, TOOLS, TOOLS)
    location = setup.take_in()
    setup.post(f"{location}/auslesen")
    [finding] = aborted_findings(setup)
    data = {
        "year": "2025",
        "kind": finding.kind,
        "target": finding.identity[1],
        "fingerprint": finding.fingerprint,
        "note": "bekannt",
    }
    response = setup.client.post("/befunde/ausblenden", data=data, headers=ORIGIN)
    assert response.status_code < 400
    assert aborted_findings(setup) == []
    setup.post(f"{location}/auslesen")
    assert len(setup.store.state().of_kind(AbortedExtraction)) == 1
    [back] = aborted_findings(setup)
    assert back.fingerprint != finding.fingerprint


def test_aborted_extraction_finding_shows_in_every_year(tmp_path: Path) -> None:
    from moarcoal.values.engine import Values

    setup = make(tmp_path, TOOLS)
    setup.post(f"{setup.take_in()}/auslesen")
    values = Values([REGISTRATION], setup.store.state())
    for year in (2019, 2025, 2031):
        visible = values.finding_list("anna", year).visible
        assert [f.kind for f in visible if f.kind == "claude_tools"] == ["claude_tools"]


def test_failed_recording_of_the_abort_is_said_on_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = make(tmp_path, TOOLS)
    location = setup.take_in()

    def reject(changes: Sequence[Change]) -> Rejected:
        return Rejected({})

    monkeypatch.setattr(setup.store, "apply", reject)
    response = setup.post(f"{location}/auslesen")
    assert response.status_code == 409
    assert "Claude meldet Werkzeuge." in response.text
    assert "nicht festgehalten" in response.text


def test_extract_and_confirm_redirect_into_the_documents_tab(tmp_path: Path) -> None:
    setup = make(tmp_path, answer())
    location = setup.take_in()
    tab = f"/belege/dokumente?dokument={setup.document().id}"
    assert setup.post(f"{location}/auslesen").headers["location"] == tab
    assert setup.post(f"{location}/bestaetigen", all="1").headers["location"] == tab
    page = setup.client.get(tab).text  # Kopf und Vorschau im selben Reiter, ohne Link „Dokument“
    assert "Alle Felder sind bestätigt." in page and "Seite 1, Zeile 4" in page
    assert '<ul class="vorschlag">' in page and 'class="vorschau"' in page
    assert "<table" not in page


def test_taken_in_file_shows_the_document_head_in_the_ablage_tab(tmp_path: Path) -> None:
    setup = make(tmp_path, answer())
    setup.take_in()
    page = setup.client.get(f"/belege?stand=alle&datei={SHA}").text
    assert f"/dokumente/{setup.document().id}/auslesen" in page
    assert f"/dokumente/{setup.document().id}/aendern" in page
    assert 'class="vorschau"' in page
    assert f'href="/dokumente/{setup.document().id}">Dokument</a>' not in page
