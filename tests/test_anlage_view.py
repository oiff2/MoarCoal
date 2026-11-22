"""Tests: die Anlage-Ansicht liefert die Zeilen des Felds und die Sonderteile, ohne HTTP (#220).

Geprüft wird über `anlage_view` an einer erfundenen Anlage KAP mit je einem Feld jeder Art und über
die angemeldeten Anlagen für die Sonderteile; nur erfundene Werte.
"""

import ast
import datetime
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading, registration
from moarcoal.modules.tax_year.anlage_est1a import ANLAGE_EST1A
from moarcoal.modules.tax_year.anlage_sa import ANLAGE_SA
from moarcoal.modules.tax_year.anlage_view import (
    AnlageView,
    Captures,
    FieldRow,
    InputContent,
    NoContent,
    TextContent,
    ValueContent,
    anlage_view,
)
from moarcoal.modules.tax_year.anlage_vor import ANLAGE_VOR, WORK_EMPLOYEE_PENSION
from moarcoal.modules.tax_year.anlagen import Anlage, YearAnlage, year_anlagen
from moarcoal.modules.tax_year.assessment import COMMUTE_DAYS
from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment
from moarcoal.modules.tax_year.church_tax_view import ChurchView, sent_form
from moarcoal.modules.tax_year.entries import FormInput, YearPersonInput
from moarcoal.modules.tax_year.field_checks import FieldCheck
from moarcoal.modules.tax_year.fields import (
    Computed,
    FieldMeaning,
    FormField,
    NotComputed,
    Rounding,
    TextSource,
    TypedInput,
)
from moarcoal.modules.tax_year.protocol_check import latest_reading
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.modules.tax_year.snapshot_check import snapshot_on_filing
from moarcoal.modules.tax_year.special_parts import PageParams, Place, SpecialPart
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Document,
    Entry,
    Proposal,
    Put,
    Snapshot,
    State,
)
from moarcoal.storage.proposals import ProposalField
from moarcoal.values.calculation import Calculation
from moarcoal.values.findings import Finding, Severity
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    NotYetComputable,
    Period,
    Unit,
    ValueKey,
    ValueLocator,
    ValueRef,
)
from moarcoal.values.testing import evaluate

USER = "anna"
NO_PARAMS = PageParams()
YEAR = 2025
STRUCTURES = Path(__file__).parent / "fixtures" / "strukturen"  # erfundene Struktur der KAP 2025

CHOICE = TypedInput(("Ja", "Nein"))
TEXT = TextSource(
    lambda details, entry, year: None if entry is None else entry.occupation,
    why_not=lambda details, entry, year: "Beruf fehlt in der Eingabe",
)


def ten_euros(calculation: Calculation, field: FormField) -> Amount:
    return Amount.eur_cents(1000)


def unknown(calculation: Calculation, field: FormField) -> Amount:
    calculation.not_yet("Es fehlt eine Angabe")


MONEY = FieldMeaning(
    "E0900005",
    Computed(Unit.EUR, Rounding.EURO_CENTS, ten_euros, assessment=(COMMUTE_DAYS,)),
    ValueKey("tax_year.kap_demo"),
)
MISSING = FieldMeaning(
    "E0900004", Computed(Unit.EUR, Rounding.EURO_CENTS, unknown), ValueKey("tax_year.kap_missing")
)
CATALOG = (
    FieldMeaning("E0900001", CHOICE),
    FieldMeaning("E0900002", TEXT),
    FieldMeaning("E0900003", NotComputed()),
    MISSING,
    MONEY,
)
KAP = Anlage("KAP", {YEAR: CATALOG}, structure_directory=STRUCTURES)
BY_ID = {f.elster_id: f for f in KAP.fields[YEAR]}


def line(elster_id: str, content: str) -> ProtocolLine:
    return ProtocolLine(
        elster_id=elster_id,
        form="KAP",
        form_line="7",
        label="Beispiel",
        content=content,
        index="1_1-1-1",
        data_name=f"id-KAP-Angaben-Beispiel-{elster_id}_usb1_1-1-1",
    )


def protocol(*lines: ProtocolLine) -> list[Entry]:
    document = Document(
        owner=USER,
        site="Belege",
        path="p.html",
        sha256=f"{1:064x}",
        document_kind="transfer_protocol",
        period_start=datetime.date(YEAR, 1, 1),
        period_end=datetime.date(YEAR, 12, 31),
        taken_in_at=datetime.datetime(YEAR + 1, 3, 1, tzinfo=datetime.UTC),
    )
    reading = ProtocolReading(
        owner=USER, document=document.address, year=YEAR, reader_version=2, lines=lines
    )
    return [document, reading]


def person(**more: str) -> YearPersonInput:
    return YearPersonInput(owner=USER, year=YEAR, **more)


def no_links(refs: Iterable[ValueRef]) -> list[tuple[str, str]]:
    return []


def view(
    entries: Sequence[Entry] = (),
    *,
    anlagen: tuple[Anlage, ...] = (KAP,),
    form: str = "KAP",
    slug: str | None = None,
    findings: Sequence[Finding] = (),
    captures: Captures = no_links,
    params: PageParams = NO_PARAMS,
) -> AnlageView | None:
    module = registration(anlagen)
    state = ModuleState(State({e.address: e for e in entries}), module, USER)
    values = evaluate([module], entries)
    found = year_anlagen(anlagen, YEAR, latest_reading(state, YEAR))
    anlage = next(a for a in found if a.form == form)
    return anlage_view(state, values, findings, captures, anlage, slug, params)


def rows_of(shown: AnlageView | None) -> dict[str, FieldRow]:
    assert shown is not None
    return {row.field.elster_id: row for row in shown.rows}


def year_anlage_of(shown: AnlageView | None) -> YearAnlage:
    assert shown is not None
    return shown.anlage


# --- Zeilen des Felds: Inhalt je Art ---------------------------------------------------------


def test_a_row_per_catalog_field_with_headings_and_the_unit_of_the_structure() -> None:
    shown = view()

    assert shown is not None
    assert [r.field.elster_id for r in shown.rows] == [
        "E0900001",
        "E0900002",
        "E0900003",
        "E0900004",
        "E0900005",
    ]
    first, *_, last = shown.rows
    assert first.headings == ("Abschnitt",)  # die erste Zeile eröffnet die Überschrift
    assert [r.headings for r in shown.rows[1:]] == [()] * 4  # sie wiederholt sich nicht
    assert (first.unit, last.unit) == ("", "€")
    assert shown.page.title == "10 - Erträge" and year_anlage_of(shown).form == "KAP"


def test_a_computed_field_shows_the_result_and_the_links_to_capture() -> None:
    asked: list[list[ValueRef]] = []

    def captures(refs: Iterable[ValueRef]) -> list[tuple[str, str]]:
        asked.append(list(refs))
        return [("Erfassen", "/erfassen")]

    content = rows_of(view(captures=captures))["E0900005"].content

    assert isinstance(content, ValueContent)
    assert isinstance(content.result, ExposedValue)
    assert content.result.amount == Amount.eur_cents(1000)
    assert content.links == (("Erfassen", "/erfassen"),)
    assert not content.whole_euros
    assert asked  # gefragt wird nach den fremden Werten des Ergebnisses


def test_a_computed_field_that_is_not_yet_computable_shows_why() -> None:
    content = rows_of(view())["E0900004"].content

    assert isinstance(content, ValueContent)
    assert isinstance(content.result, NotYetComputable)
    assert content.result.reason == "Es fehlt eine Angabe"


def test_a_typed_field_shows_the_saved_text_or_nothing_yet() -> None:
    before = rows_of(view())["E0900001"].content
    saved = FormInput(owner=USER, year=YEAR, elster_id="E0900001", content="Ja")
    after = rows_of(view([saved]))["E0900001"].content

    assert before == InputContent(CHOICE, None)
    assert after == InputContent(CHOICE, "Ja")


def test_the_input_of_another_year_does_not_count() -> None:
    other = FormInput(owner=USER, year=YEAR - 1, elster_id="E0900001", content="Ja")

    assert rows_of(view([other]))["E0900001"].content == InputContent(CHOICE, None)


def test_a_text_field_shows_the_text_or_the_reason_it_is_missing() -> None:
    without = rows_of(view())["E0900002"].content
    with_text = rows_of(view([person(occupation="Gärtner")]))["E0900002"].content

    assert without == TextContent(None, "Beruf fehlt in der Eingabe")
    assert with_text == TextContent("Gärtner", "Beruf fehlt in der Eingabe")


def test_a_field_that_is_not_computed_shows_nothing() -> None:
    assert rows_of(view())["E0900003"].content == NoContent()


# --- Gegenproben -------------------------------------------------------------------------------


def test_without_a_protocol_snapshot_or_assessment_there_are_no_checks() -> None:
    assert all(row.checks == () for row in view().rows)  # type: ignore[union-attr]


def test_the_protocol_side_shows_the_printed_content_and_whether_it_fits() -> None:
    shown = view(protocol(line("E0900005", "10,00"), line("E0900002", "Gärtner")))

    assert rows_of(shown)["E0900005"].checks == (
        FieldCheck("Laut Protokoll", "10,00 €", fits=True),
    )
    assert rows_of(shown)["E0900001"].checks == (FieldCheck("Laut Protokoll", "–"),)


def test_a_finding_of_the_field_makes_its_check_deviate() -> None:
    ref = ValueRef(ValueKey("tax_year.kap_demo"), USER, Period.year(YEAR), None)
    finding = Finding(
        "tax_year.protocol_deviation", Severity.WARNING, ref, "Das Protokoll weicht ab."
    )

    shown = view(protocol(line("E0900005", "9,00")), findings=[finding])

    (check,) = rows_of(shown)["E0900005"].checks
    assert check.deviation == "Das Protokoll weicht ab." and check.severity is Severity.WARNING


def test_the_snapshot_is_frozen_per_field_and_the_view_carries_it() -> None:
    module = registration((KAP,))
    entries = protocol(line("E0900005", "10,00"))
    document, reading = entries
    assert isinstance(document, Document)
    values = evaluate([module], entries)
    (change,) = snapshot_on_filing(document, [reading], values, (KAP,))
    assert isinstance(change, Put) and isinstance(change.entry, Snapshot)

    shown = view([*entries, change.entry])

    assert shown is not None and shown.snapshot == change.entry
    sides = {c.side: c for c in rows_of(shown)["E0900005"].checks}
    assert sides["Bei Abgabe"] == FieldCheck("Bei Abgabe", "10,00 €", fits=True)
    assert "Bei Abgabe" not in {
        c.side for c in rows_of(shown)["E0900001"].checks
    }  # nicht berechnet
    assert view(entries).snapshot is None  # type: ignore[union-attr]


def test_the_assessment_side_shows_the_confirmed_amount() -> None:
    document = Document(
        owner=USER,
        site="Belege",
        path="b.pdf",
        sha256=f"{2:064x}",
        document_kind="assessment",
        period_start=datetime.date(YEAR, 1, 1),
        period_end=datetime.date(YEAR, 12, 31),
        taken_in_at=datetime.datetime(YEAR + 1, 5, 1, tzinfo=datetime.UTC),
    )
    proposal = Proposal(
        owner=USER,
        document=document.address,
        template_version=1,
        fields={COMMUTE_DAYS: ProposalField(value="10", location="S. 2", confirmed=True)},
        raw="{}",
        created_at=datetime.datetime(YEAR + 1, 5, 1, tzinfo=datetime.UTC),
    )

    shown = view([document, proposal])

    (check,) = rows_of(shown)["E0900005"].checks
    assert check.side == "Laut EStB" and check.shown == "10,00 €"
    assert rows_of(shown)["E0900001"].checks == (FieldCheck("Laut EStB", "–"),)  # ohne Position


# --- Seite -------------------------------------------------------------------------------------


def test_a_page_that_does_not_exist_gives_none_and_no_slug_means_the_first_page() -> None:
    assert view(slug="gibt-es-nicht") is None
    first, named = view(), view(slug="10")
    assert first is not None and named is not None
    assert first.page == named.page


# --- Sonderteile -------------------------------------------------------------------------------


def invented_parts() -> tuple[Anlage, list[PageParams]]:
    seen: list[PageParams] = []

    def top(state: ModuleState, year: int, params: PageParams) -> object:
        seen.append(params)
        return f"oben {year} {state.user}"

    def bottom(state: ModuleState, year: int, params: PageParams) -> object:
        return "unten"

    parts = (
        SpecialPart("kap/_oben.html", Place.TOP, top),
        SpecialPart("kap/_unten.html", Place.BOTTOM, bottom),
    )
    return Anlage("KAP", {YEAR: CATALOG}, parts=parts, structure_directory=STRUCTURES), seen


def test_a_special_part_gets_state_year_and_request_parameters_and_sits_where_it_says() -> None:
    anlage, seen = invented_parts()
    params = PageParams(entry="ABCDEFGHIJ")

    shown = view(anlagen=(anlage,), params=params)

    assert shown is not None
    assert [(part.template, part.place, data) for part, data in shown.parts] == [
        ("kap/_oben.html", Place.TOP, f"oben {YEAR} {USER}"),
        ("kap/_unten.html", Place.BOTTOM, "unten"),
    ]
    assert seen == [params]


def test_an_anlage_without_parts_has_none() -> None:
    shown = view()

    assert shown is not None and shown.parts == ()


def test_est1a_carries_the_note_on_its_first_page_only() -> None:
    entries = [person(note="Beispielnotiz")]
    first = view(entries, anlagen=ANLAGEN, form="ESt1A")
    other = view(entries, anlagen=ANLAGEN, form="ESt1A", slug="4")

    assert first is not None and other is not None
    assert [(part.place, data) for part, data in first.parts] == [(Place.TOP, "Beispielnotiz")]
    assert other.parts == ()


def test_est1a_without_a_note_has_none_to_show() -> None:
    shown = view(anlagen=ANLAGEN, form="ESt1A")

    assert shown is not None
    assert [data for _, data in shown.parts] == [None]


def test_sa_carries_the_church_tax_payments_at_the_bottom() -> None:
    payment = ChurchTaxPayment(
        owner=USER,
        date=datetime.date(YEAR, 4, 1),
        amount_cents=12345,
        benefit_type="Kirchensteuer",
    )

    shown = view([payment], anlagen=ANLAGEN, form="SA")

    assert shown is not None
    ((part, data),) = shown.parts
    assert part.place is Place.BOTTOM
    assert isinstance(data, ChurchView)
    assert [p.id for p, _, _ in data.payments] == [payment.id]
    assert data.payments[0][1].open is False and data.new.errors == ()


def test_the_church_tax_form_state_comes_as_a_request_parameter() -> None:
    payment = ChurchTaxPayment(
        owner=USER,
        date=datetime.date(YEAR, 4, 1),
        amount_cents=12345,
        benefit_type="Kirchensteuer",
    )
    sent = sent_form("", {"amount": "x"}, ["Betrag: ungültig"])

    opened = view([payment], anlagen=ANLAGEN, form="SA", params=PageParams(entry=payment.id))
    rejected = view([payment], anlagen=ANLAGEN, form="SA", params=PageParams(sent=sent))

    assert opened is not None and rejected is not None
    assert isinstance(opened.parts[0][1], ChurchView) and isinstance(
        rejected.parts[0][1], ChurchView
    )
    assert opened.parts[0][1].payments[0][1].open is True
    assert rejected.parts[0][1].new == sent


def test_every_anlage_but_est1a_and_sa_has_no_special_part() -> None:
    assert [a.form for a in ANLAGEN if a.parts] == ["ESt1A", "SA"]
    assert ANLAGE_EST1A.parts and ANLAGE_SA.parts


def test_a_text_field_with_content_fits_when_the_protocol_shows_something() -> None:
    lines = protocol(line("E0900002", "Gärtner"))

    with_text = rows_of(view([*lines, person(occupation="Gärtner")]))["E0900002"]
    without = rows_of(view(lines))["E0900002"]

    assert with_text.checks == (FieldCheck("Laut Protokoll", "Gärtner", fits=True),)
    assert without.checks == (FieldCheck("Laut Protokoll", "Gärtner"),)  # ohne Text kein Urteil


def test_a_whole_euro_field_says_so_and_carries_the_rounded_amount() -> None:
    payment = ChurchTaxPayment(
        owner=USER, date=datetime.date(YEAR, 4, 1), amount_cents=12345, benefit_type="Kirche"
    )

    shown = view([payment], anlagen=ANLAGEN, form="SA")

    paid = rows_of(shown)["E0107601"].content
    assert isinstance(paid, ValueContent) and paid.whole_euros
    assert isinstance(paid.result, ExposedValue) and paid.result.amount == Amount.eur_cents(12400)


# --- Seite gerendert: eine Probe je Form des Inhalts und je Sonderteil -------------------------

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}


def client(tmp_path: Path) -> httpx.Client:
    modules = [
        registration((KAP, ANLAGE_EST1A, ANLAGE_SA)) if m.key == "tax_year" else m for m in MODULES
    ]
    app = make_app(PORT, tmp_path, modules, user=USER)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_the_page_renders_every_form_of_content(tmp_path: Path) -> None:
    http = client(tmp_path)
    http.post("/steuerjahr/person/2025", data={"occupation": "Gärtner"}, headers=ORIGIN)

    page = http.get("/steuerjahr/anlage-kap/2025").text

    assert 'id="eingabe-E0900001"' in page and '<option value="Ja">' in page  # Eingabe
    assert "noch nicht angegeben" in page
    assert '<span class="inhalt">Gärtner</span>' in page  # Text
    assert "10,00 €" in page  # Wert
    assert "Es fehlt eine Angabe" in page  # Wert, noch nicht berechenbar
    assert page.count("wird noch nicht berechnet") == 1  # nichts: das nicht berechnete Feld
    for number in "34567":
        assert f"Z. {number}</span>" in page


def test_the_page_renders_the_reason_a_text_is_missing(tmp_path: Path) -> None:
    page = client(tmp_path).get("/steuerjahr/anlage-kap/2025").text

    assert "Beruf fehlt in der Eingabe" in page


def test_the_note_of_est1a_sits_on_top_of_the_first_page_only(tmp_path: Path) -> None:
    http = client(tmp_path)
    assert "keine Notiz" in http.get("/steuerjahr/anlage-est1a/2025").text
    http.post("/steuerjahr/person/2025", data={"note": "Beispielnotiz"}, headers=ORIGIN)

    first = http.get("/steuerjahr/anlage-est1a/2025").text
    other = http.get("/steuerjahr/anlage-est1a/2025/4").text

    assert "Beispielnotiz" in first and "wird nicht übermittelt" in first
    assert first.index("Beispielnotiz") < first.index('id="feld-')
    assert "Beispielnotiz" not in other and "Bearbeitungsnotiz" not in other


def test_the_church_tax_payments_sit_below_the_fields_of_sa(tmp_path: Path) -> None:
    page = client(tmp_path).get("/steuerjahr/anlage-sa/2025").text

    assert page.rindex('id="feld-') < page.index("Neue Kirchensteuerzahlung")


def test_the_pure_view_imports_neither_fastapi_nor_the_pages_of_the_binding() -> None:
    """Prinzip 4: Anlage-Ansicht, Sonderteile und Ansicht der Kirchensteuer binden weder FastAPI
    noch Routen und Helfer der Anbindung ein; erlaubt ist nur `moarcoal.web.links` (Adressen).
    (Das Paket `tax_year` selbst und `registration` laden FastAPI; geprüft werden die eigenen
    Importe der Dateien.)"""
    folder = Path(__file__).parent.parent / "src" / "moarcoal" / "modules" / "tax_year"
    pure = ("anlage_view.py", "special_parts.py", "church_tax_view.py")
    forbidden = ("fastapi", "starlette", "moarcoal.web", "moarcoal.modules.tax_year.pages")
    allowed = {"moarcoal.web.links"}
    for name in pure:
        tree = ast.parse((folder / name).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        bad = [
            m
            for m in imported
            if m not in allowed
            and (m.startswith(forbidden) or m.endswith(("church_tax_pages", "tax_year.pages")))
        ]
        assert bad == [], f"{name} importiert {bad}"


def test_vor_shows_the_short_catalog_title_in_the_locator_of_a_foreign_value() -> None:
    """Auch auf Anlage VOR nennt die Fundstelle eines Werts aus Arbeit den Katalogtitel (#229)."""
    document = Document(
        owner=USER,
        site="Belege",
        path="lstb.xml",
        sha256=f"{2:064x}",
        document_kind="wage_tax_certificate",
        period_start=datetime.date(YEAR, 1, 1),
        period_end=datetime.date(YEAR, 12, 31),
        taken_in_at=datetime.datetime(YEAR + 1, 3, 1, tzinfo=datetime.UTC),
    )
    certificate = WageTaxCertificate(
        owner=USER,
        document=document.address,
        reader_version=3,
        year=YEAR,
        employee_pension_cents=123456,
        places={"employee_pension": "id-Beispiel-employee-pension"},
    )
    module = registration((ANLAGE_VOR,))
    entries = [document, certificate]
    state = ModuleState(State({e.address: e for e in entries}), module, USER)
    values = evaluate([WORK, module], entries)
    anlage = next(a for a in year_anlagen((ANLAGE_VOR,), YEAR, None) if a.form == "VOR")
    page = next(p for p in anlage.pages for r in p.rows if r.field.elster_id == "E2000401")
    shown = anlage_view(state, values, (), no_links, anlage, page.slug, NO_PARAMS)

    content = rows_of(shown)["E2000401"].content  # Nr. 23 a/b, ein Wert aus Arbeit
    assert isinstance(content, ValueContent)
    assert isinstance(content.result, ExposedValue)
    (item,) = content.result.items
    assert isinstance(item.locator, ValueLocator)
    title = next(d.entry.title for d in WORK.values if d.entry.key == WORK_EMPLOYEE_PENSION)
    assert title != WORK_EMPLOYEE_PENSION  # ein Katalogtitel, nicht der Schlüssel
    assert item.locator.label == f"Wert {title}"
    assert not re.search(r"Wert [a-z_]+\.[a-z_]+", item.locator.label)
