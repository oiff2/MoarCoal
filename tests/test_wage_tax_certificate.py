"""Tests: Dokumentart Lohnsteuerbescheinigung (eDaten) einlesen, Felder 4 bis 7 (nur tmp_path)."""

import datetime
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal.documents import IntakeRejected, ReadInError, TakenIn, take_in
from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading
from moarcoal.modules.tax_year.anlage_n import (
    N_GROSS_WAGES,
    N_GROSS_WAGES_SINGLE,
    N_INCOME_TAX,
    N_REFUND_FLAT_TAXED,
    N_REFUND_TAX_FREE,
    N_SOLI,
    N_TAX_CLASS,
)
from moarcoal.modules.tax_year.anlage_vor import (
    VOR_EMPLOYEE_CARE,
    VOR_EMPLOYEE_HEALTH,
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_SUBSIDY_CARE,
    VOR_SUBSIDY_PRIVATE_HEALTH,
    VOR_SUBSIDY_PUBLIC_HEALTH,
    VOR_UNEMPLOYMENT,
)
from moarcoal.modules.tax_year.protocol_check import DEVIATION, MISSING
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import WAGE_TAX_CERTIFICATE, WageTaxCertificate
from moarcoal.modules.work.wage_tax.reading import READER_VERSION, read_in_wage_tax_certificate
from moarcoal.modules.work.wage_tax.values import (
    BENEFITS_FLAT_TAXED,
    BENEFITS_TAX_FREE,
    CERTIFICATE_LINES,
    EMPLOYEE_CARE,
    EMPLOYEE_HEALTH,
    SUBSIDY_PUBLIC_HEALTH,
)
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    Entry,
    Store,
    entry_checksum,
    open_store,
)
from moarcoal.values.model import (
    Amount,
    Backing,
    ExposedValue,
    NotYetComputable,
    Period,
    Unit,
    ValueRef,
)
from moarcoal.values.testing import evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "lohnsteuerbescheinigung_2025.html"
PROTOCOL = Path(__file__).parent / "fixtures" / "uebertragungsprotokoll_2025.html"
USER = "anna"
YEAR = Period.year(2025)
KINDS = {k.key: k for r in MODULES for k in r.document_kinds}
FIELDS_4_TO_7 = (N_TAX_CLASS, N_GROSS_WAGES, N_INCOME_TAX, N_SOLI)
FIELDS_17_18 = (N_REFUND_TAX_FREE, N_REFUND_FLAT_TAXED)
FIELDS_VOR = (
    VOR_EMPLOYEE_PENSION,
    VOR_EMPLOYER_PENSION,
    VOR_SUBSIDY_PRIVATE_HEALTH,
    VOR_SUBSIDY_CARE,
    VOR_UNEMPLOYMENT,
)
FIELDS_VOR_NOT_CERTIFIED = (VOR_SUBSIDY_PUBLIC_HEALTH, VOR_EMPLOYEE_HEALTH, VOR_EMPLOYEE_CARE)


def make_document(year: int | None = 2025) -> Document:
    return Document(
        owner=USER,
        site="Belege",
        path="lstb.html",
        sha256="0" * 64,
        document_kind=WAGE_TAX_CERTIFICATE.key,
        period_start=datetime.date(year, 1, 1) if year else None,
        period_end=datetime.date(year, 12, 31) if year else None,
    )


def read(content: str | bytes | None = None, year: int | None = 2025) -> WageTaxCertificate:
    data = FIXTURE.read_bytes() if content is None else content
    data = data.encode() if isinstance(data, str) else data
    (entry,) = read_in_wage_tax_certificate(make_document(year), data)
    assert isinstance(entry, WageTaxCertificate)
    return entry


def test_unexpected_format_names_the_document_kind() -> None:
    with pytest.raises(
        ReadInError,
        match=r"Unerwartetes Format \(sieht nach einem PDF aus\).*Lohnsteuerbescheinigung",
    ):
        read(b"%PDF-1.7\n1 0 obj")
    for content in ("<p>nichts</p>", "nur Text"):
        with pytest.raises(
            ReadInError,
            match=r"Unerwartetes Format \(keine HTML-Datei.*Lohnsteuerbescheinigung",
        ):
            read(content)
    with pytest.raises(ReadInError, match="Dokumentart Lohnsteuerbescheinigung"):
        read("<!-- Belegart: E10 --><p>x</p>")


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def without(path: str) -> str:
    """Die Fixture ohne die Zeile mit `path`."""
    rows = fixture_text().splitlines()
    return "\n".join(r for r in rows if f"-{path}_usb" not in r)


def test_reads_the_four_values_exactly_with_their_places() -> None:
    entry = read()

    assert (entry.year, entry.tax_class, entry.gross_wages_cents) == (2025, 1, 4_567_890)
    assert (entry.income_tax_cents, entry.soli_cents) == (654_321, 0)
    assert entry.places["gross_wages"] == (
        "id-VaSt_LStB-Besteuerungsgrund-BruttoArbLohn_usb1_1-1-1"
    )
    assert {"tax_class", "gross_wages", "income_tax", "soli"} <= set(entry.places)


def test_reads_nr_22_to_24_and_27_exactly_with_their_places() -> None:
    entry = read()

    assert entry.employer_pension_cents == 432_109  # Nr. 22 a/b
    assert entry.employee_pension_cents == 432_110  # Nr. 23 a/b
    assert entry.subsidy_private_health_cents == 12_345  # Nr. 24 b
    assert entry.subsidy_care_cents == 6_789  # Nr. 24 c
    assert entry.unemployment_cents == 54_321  # Nr. 27
    assert entry.places["unemployment"] == (
        "id-VaSt_LStB-Besteuerungsgrund-ArbnAnteilArblVers_usb1_1-1-1"
    )
    assert {"employer_pension", "employee_pension", "subsidy_care"} <= set(entry.places)


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("Besteuerungsgrund-ArbgAnteilRenVers", "employer_pension"),
        ("Besteuerungsgrund-ArbnAnteilRenVers", "employee_pension"),
        ("Besteuerungsgrund-StFreiPrKrankVers", "subsidy_private_health"),
        ("Besteuerungsgrund-StFreiGePflegVers", "subsidy_care"),
        ("Besteuerungsgrund-ArbnAnteilArblVers", "unemployment"),
    ],
)
def test_missing_vorsorge_number_stays_empty_not_zero(path: str, field: str) -> None:
    entry = read(without(path))
    assert getattr(entry, f"{field}_cents") is None and field not in entry.places


def test_repeated_vorsorge_path_is_not_guessed() -> None:
    html = fixture_text()
    row = next(r for r in html.splitlines() if "ArbnAnteilArblVers" in r)
    with pytest.raises(ReadInError, match="2-mal"):
        read(html.replace(row, row + "\n" + row.replace("usb1_", "usb2_")))


def test_wrong_year_is_rejected() -> None:
    with pytest.raises(ReadInError, match="Steuerjahr 2025"):
        read(year=2024)


def test_other_belegart_is_rejected() -> None:
    with pytest.raises(ReadInError, match="Dokumentart Lohnsteuerbescheinigung"):
        read(PROTOCOL.read_bytes())


def test_document_without_period_is_rejected() -> None:
    with pytest.raises(ReadInError, match="Bezugszeitraum"):
        read(year=None)


def test_gross_wages_are_required() -> None:
    with pytest.raises(ReadInError, match="Bruttoarbeitslohn"):
        read(without("Besteuerungsgrund-BruttoArbLohn"))


@pytest.mark.parametrize("text", ["abc", "-1,00", "45.678,901"])
def test_amount_must_be_exact_euro_and_cent(text: str) -> None:
    with pytest.raises(ReadInError, match="Bruttoarbeitslohn"):
        read(fixture_text().replace("45.678,90", text))


def test_repeated_path_is_not_guessed() -> None:
    html = fixture_text()
    row = next(r for r in html.splitlines() if "Steuerklasse-Klasse" in r)
    again = row.replace("usb1_", "usb2_").replace(">1<", ">3<")
    with pytest.raises(ReadInError, match="2-mal"):
        read(html.replace(row, row + "\n" + again))


def test_tax_class_must_be_one_to_six() -> None:
    with pytest.raises(ReadInError, match="Steuerklasse"):
        read(re.sub(r"<span>1</span>", "<span>7</span>", fixture_text(), count=1))


def test_missing_optional_value_stays_empty_not_zero() -> None:
    entry = read(without("Besteuerungsgrund-Soli"))
    assert entry.soli_cents is None and "soli" not in entry.places


def with_unknown(path: str = "Besteuerungsgrund-Unbekannt") -> str:
    """Die Fixture mit einer Zeile mehr, unter einem Pfad, den die Einlese-Regel nicht kennt."""
    html = fixture_text()
    row = next(r for r in html.splitlines() if "Besteuerungsgrund-Soli_usb" in r)
    return html.replace(row, row + "\n" + row.replace("Besteuerungsgrund-Soli", path))


def test_known_file_has_no_unrecognized_paths() -> None:
    entry = read()
    assert entry.unrecognized == [] and entry.reader_version == READER_VERSION


def test_paths_the_reader_does_not_know_are_kept_as_unrecognized() -> None:
    entry = read(with_unknown())
    assert entry.unrecognized == ["Besteuerungsgrund-Unbekannt"]


# --- im Betrieb: aufnehmen, Werte, Felder 4 bis 7, Abgleich -----------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "lstb.html")
    return folder


@pytest.fixture
def store(tmp_path: Path, site: Path) -> Store:
    once = {WAGE_TAX_CERTIFICATE.key: WAGE_TAX_CERTIFICATE.title}
    return open_store(
        tmp_path / "daten", [*WORK.kinds, *TAX_YEAR.kinds], {"Belege": site}, once_per_period=once
    )


def take(store: Store, path: str = "lstb.html", year: int = 2025) -> TakenIn | IntakeRejected:
    return take_in(store, KINDS, USER, "Belege", path, WAGE_TAX_CERTIFICATE.key, year)


def entries(store: Store) -> list[Entry]:
    return list(store.state().entries.values())


def test_take_in_stores_document_and_reading_and_allows_one_per_year(
    store: Store, site: Path
) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)
    (entry,) = taken.entries
    assert isinstance(entry, WageTaxCertificate) and entry.document == taken.document.address

    (site / "zweite.html").write_text(fixture_text() + "<!-- 2 -->", encoding="utf-8")
    assert isinstance(take(store, "zweite.html"), IntakeRejected)


def test_deleting_the_document_takes_the_certificate_along_and_the_file_can_be_taken_in_again(
    store: Store, site: Path
) -> None:
    first = take(store)
    assert isinstance(first, TakenIn)
    (old,) = first.entries
    (site / "zweite.html").write_text(fixture_text() + "<!-- 2 -->", encoding="utf-8")
    assert isinstance(take(store, "zweite.html"), IntakeRejected)  # solange das Dokument da ist

    deleted = store.apply([Delete(first.document.address, entry_checksum(first.document))])

    assert isinstance(deleted, Applied)
    assert store.state().of_kind(WageTaxCertificate) == []
    again = take(store)  # dieselbe Datei, das Jahr ist wieder frei
    assert isinstance(again, TakenIn)
    (new,) = store.state().of_kind(WageTaxCertificate)
    assert new.id != old.id and new.document == again.document.address


def test_fields_4_to_7_are_computed_from_the_certificate(store: Store) -> None:
    assert isinstance(take(store), TakenIn)
    values = evaluate(MODULES, entries(store))

    def get(key: str) -> ExposedValue:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, ExposedValue), result
        return result

    assert get(N_TAX_CLASS).amount == Amount.of(1, Unit.TAX_CLASS)
    gross = get(N_GROSS_WAGES)
    assert gross.amount == Amount.eur_cents(4_567_800)  # Einnahme: abgerundet auf ganze Euro
    assert get(N_GROSS_WAGES_SINGLE).amount == Amount.eur_cents(4_567_890)  # je Bescheinigung: Cent
    assert get(N_INCOME_TAX).amount == Amount.eur_cents(654_321)
    assert get(N_SOLI).amount == Amount.eur_cents(0)  # bescheinigt 0,00, kein fehlender Wert
    assert gross.backing is Backing.PROVEN


def test_without_certificate_the_fields_are_not_yet_computable_never_zero(store: Store) -> None:
    values = evaluate(MODULES, entries(store))
    for key in FIELDS_4_TO_7 + FIELDS_17_18:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "Lohnsteuerbescheinigung" in str(result)


def test_value_missing_in_the_certificate_is_not_yet_computable(store: Store, site: Path) -> None:
    (site / "ohne.html").write_text(without("Besteuerungsgrund-Soli"), encoding="utf-8")
    assert isinstance(take(store, "ohne.html"), TakenIn)

    values = evaluate(MODULES, entries(store))

    result = values.get(N_SOLI, USER, YEAR)
    assert isinstance(result, NotYetComputable)
    assert "Solidaritätszuschlag nicht" in str(result)
    assert isinstance(values.get(N_INCOME_TAX, USER, YEAR), ExposedValue)


def test_employer_benefits_not_certified_are_zero_with_reason(store: Store) -> None:
    assert isinstance(take(store), TakenIn)
    values = evaluate(MODULES, entries(store))

    for field, source, number in (
        (N_REFUND_TAX_FREE, BENEFITS_TAX_FREE, "17"),
        (N_REFUND_FLAT_TAXED, BENEFITS_FLAT_TAXED, "18"),
    ):
        result = values.get(field, USER, YEAR)
        assert isinstance(result, ExposedValue), result
        assert result.amount == Amount.eur_cents(0)
        assert result.backing is Backing.PROVEN
        work = values.get(source, USER, YEAR)
        assert isinstance(work, ExposedValue)
        steps = " ".join(step.text for step in work.workings.steps)
        assert f"Nr. {number} ist nicht bescheinigt" in steps


def test_unrecognized_path_leaves_employer_benefits_not_yet_computable(
    store: Store, site: Path
) -> None:
    (site / "neu.html").write_text(with_unknown(), encoding="utf-8")
    assert isinstance(take(store, "neu.html"), TakenIn)

    values = evaluate(MODULES, entries(store))

    for key in FIELDS_17_18:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "Besteuerungsgrund-Unbekannt" in str(result)
    assert isinstance(values.get(N_GROSS_WAGES, USER, YEAR), ExposedValue)


def test_certificate_from_an_older_reader_leaves_employer_benefits_not_yet_computable(
    store: Store,
) -> None:
    assert isinstance(take(store), TakenIn)
    old = [
        e.model_copy(update={"reader_version": 1}) if isinstance(e, WageTaxCertificate) else e
        for e in entries(store)
    ]

    values = evaluate(MODULES, old)

    for key in FIELDS_17_18:
        assert isinstance(values.get(key, USER, YEAR), NotYetComputable)


def test_vor_fields_take_nr_22_to_24_and_27_from_the_certificate(store: Store) -> None:
    assert isinstance(take(store), TakenIn)
    values = evaluate(MODULES, entries(store))

    def get(key: str) -> ExposedValue:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, ExposedValue), result
        return result

    # Einnahme (Arbeitgeberanteil, Zuschuss) wird abgerundet, Ausgabe aufgerundet: ganze Euro
    assert get(VOR_EMPLOYER_PENSION).amount == Amount.eur_cents(432_100)
    assert get(VOR_EMPLOYEE_PENSION).amount == Amount.eur_cents(432_200)
    assert get(VOR_SUBSIDY_PRIVATE_HEALTH).amount == Amount.eur_cents(12_300)
    assert get(VOR_SUBSIDY_CARE).amount == Amount.eur_cents(6_700)
    assert get(VOR_UNEMPLOYMENT).amount == Amount.eur_cents(54_400)
    assert get(VOR_UNEMPLOYMENT).backing is Backing.PROVEN


def test_vor_fields_are_not_yet_computable_without_certificate_never_zero(store: Store) -> None:
    values = evaluate(MODULES, entries(store))
    for key in FIELDS_VOR:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "Lohnsteuerbescheinigung" in str(result)


def test_vor_field_the_certificate_does_not_state_is_not_yet_computable(
    store: Store, site: Path
) -> None:
    (site / "ohne.html").write_text(
        without("Besteuerungsgrund-StFreiGePflegVers"), encoding="utf-8"
    )
    assert isinstance(take(store, "ohne.html"), TakenIn)

    values = evaluate(MODULES, entries(store))

    result = values.get(VOR_SUBSIDY_CARE, USER, YEAR)
    assert isinstance(result, NotYetComputable)
    assert "nennt" in str(result) and "nicht" in str(result)
    assert isinstance(values.get(VOR_UNEMPLOYMENT, USER, YEAR), ExposedValue)


def test_unrecognized_path_leaves_the_a_b_fields_not_yet_computable(
    store: Store, site: Path
) -> None:
    """Nr. 22 b und 23 b haben vielleicht einen eigenen, unbekannten Pfad; dann fehlt ihr Betrag."""
    (site / "neu.html").write_text(with_unknown(), encoding="utf-8")
    assert isinstance(take(store, "neu.html"), TakenIn)

    values = evaluate(MODULES, entries(store))

    for key in (VOR_EMPLOYER_PENSION, VOR_EMPLOYEE_PENSION):
        result = values.get(key, USER, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "Besteuerungsgrund-Unbekannt" in str(result)
    assert isinstance(values.get(VOR_UNEMPLOYMENT, USER, YEAR), ExposedValue)


def test_certificate_from_an_older_reader_leaves_vor_fields_not_yet_computable(
    store: Store,
) -> None:
    assert isinstance(take(store), TakenIn)
    old = [
        e.model_copy(update={"reader_version": 2}) if isinstance(e, WageTaxCertificate) else e
        for e in entries(store)
    ]

    values = evaluate(MODULES, old)

    for key in FIELDS_VOR:
        assert isinstance(values.get(key, USER, YEAR), NotYetComputable)


def protocol_entries(contents: dict[str, str]) -> list[Entry]:
    """Ein Übertragungsprotokoll 2025 mit den Zeilen `E-Kennung -> Inhalt`."""
    document = Document(
        owner=USER,
        site="Belege",
        path="p.html",
        sha256="1" * 64,
        document_kind="transfer_protocol",
        period_start=datetime.date(2025, 1, 1),
        period_end=datetime.date(2025, 12, 31),
        taken_in_at=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
    )
    lines = tuple(
        ProtocolLine(
            elster_id=elster_id,
            form="N",
            form_line="",
            label="Beispiel",
            content=content,
            index="1_1-1-1",
            data_name=f"id-N-Beispiel-{elster_id}_usb1_1-1-1",
        )
        for elster_id, content in contents.items()
    )
    reading = ProtocolReading(
        owner=USER, document=document.address, year=2025, reader_version=2, lines=lines
    )
    return [document, reading]


def comparison(store: Store, contents: dict[str, str]) -> set[tuple[str, str]]:
    """Die Abgleichsbefunde (Art, Schlüssel) der Felder 4 bis 7 gegen ein Protokoll."""
    assert isinstance(take(store), TakenIn)
    values = evaluate(MODULES, [*entries(store), *protocol_entries(contents)])
    found = values.finding_list(USER, 2025).visible
    keys = {str(k) for k in FIELDS_4_TO_7 + FIELDS_17_18} | {str(N_GROSS_WAGES_SINGLE)}
    return {
        (f.kind, f.target.key)
        for f in found
        if f.kind in (DEVIATION, MISSING)
        and isinstance(f.target, ValueRef)
        and f.target.key in keys
    }


MATCHING = {
    "E0200002": "1",
    "E0200201": "45.678",
    "E0200204": "45.678,90",
    "E0200301": "6.543,21",
    "E0200304": "6.543,21",
    "E0200401": "0,00",
    "E0200404": "0,00",
    "E0204103": "0",
    "E0203901": "0",
}


def test_protocol_is_compared_against_the_computed_fields(store: Store) -> None:
    assert comparison(store, MATCHING) == set()


def test_deviating_protocol_gives_a_finding(store: Store) -> None:
    found = comparison(store, {**MATCHING, "E0200301": "6.500,00"})
    assert found == {(DEVIATION, str(N_INCOME_TAX))}


def test_employer_benefits_in_the_protocol_but_not_certified_give_a_finding(store: Store) -> None:
    found = comparison(store, {**MATCHING, "E0204103": "120"})
    assert found == {(DEVIATION, str(N_REFUND_TAX_FREE))}


def page_client(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url="http://127.0.0.1:4711")


def test_arbeit_shows_the_four_values_with_a_link_to_the_document(
    tmp_path: Path, site: Path
) -> None:
    root = tmp_path / "app"
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(4711, root, user=USER)
    client = page_client(app)
    empty = client.get("/arbeit?jahr=2025").text
    assert "Lohnsteuerbescheinigung" in empty and "Für 2025 ist keine" in empty

    taken = take(app.state.store)
    assert isinstance(taken, TakenIn)
    page = client.get("/arbeit?jahr=2025").text
    section = page.split("<h2>Lohnsteuerbescheinigung</h2>", 1)[1].split("</section>", 1)[0]
    for label in ("Steuerklasse", "Bruttoarbeitslohn", "Lohnsteuer", "Solidaritätszuschlag"):
        assert f"{label}:" in section
    assert "45.678,90 €" in section and "6.543,21 €" in section
    for label in (
        "Nr. 22 a/b",
        "Nr. 23 a/b",
        "Nr. 24 b",
        "Nr. 24 c",
        "Nr. 27",
    ):
        assert label in section
    assert "4.321,09 €" in section and "543,21 €" in section
    assert f'href="/belege?dokument={taken.document.id}"' in section


def test_vor_nr_24_a_25_26_not_certified_are_zero_with_reason(store: Store) -> None:
    assert isinstance(take(store), TakenIn)
    values = evaluate(MODULES, entries(store))

    for field, source, number, reason in (
        (
            VOR_SUBSIDY_PUBLIC_HEALTH,
            SUBSIDY_PUBLIC_HEALTH,
            "24 a",
            "kein Zuschuss zur gesetzlichen Krankenversicherung",
        ),
        (
            VOR_EMPLOYEE_HEALTH,
            EMPLOYEE_HEALTH,
            "25",
            "keine Beiträge zur gesetzlichen Krankenversicherung",
        ),
        (VOR_EMPLOYEE_CARE, EMPLOYEE_CARE, "26", "keine Beiträge zur sozialen Pflegeversicherung"),
    ):
        result = values.get(field, USER, YEAR)
        assert isinstance(result, ExposedValue), result
        assert result.amount == Amount.eur_cents(0)
        assert result.backing is Backing.PROVEN
        work = values.get(source, USER, YEAR)
        assert isinstance(work, ExposedValue)
        steps = " ".join(step.text for step in work.workings.steps)
        assert f"Nr. {number} ist nicht bescheinigt: {reason}" in steps


def test_vor_nr_24_a_25_26_with_unrecognized_path_are_not_yet_computable(
    store: Store, site: Path
) -> None:
    (site / "neu.html").write_text(with_unknown(), encoding="utf-8")
    assert isinstance(take(store, "neu.html"), TakenIn)

    values = evaluate(MODULES, entries(store))

    for key in FIELDS_VOR_NOT_CERTIFIED:
        result = values.get(key, USER, YEAR)
        assert isinstance(result, NotYetComputable)
        assert "Besteuerungsgrund-Unbekannt" in str(result)


def test_vor_nr_24_a_25_26_without_certificate_are_not_yet_computable(store: Store) -> None:
    values = evaluate(MODULES, entries(store))
    for key in FIELDS_VOR_NOT_CERTIFIED:
        assert isinstance(values.get(key, USER, YEAR), NotYetComputable)


def test_every_certificate_line_has_a_catalog_value_and_an_overview_row(
    tmp_path: Path, site: Path
) -> None:
    """Eine Zeile der Bescheinigung steht einmal in `CERTIFICATE_LINES`; Wertekatalog und Übersicht
    folgen daraus."""
    catalog_keys = {d.entry.key for r in MODULES if r.key == "work" for d in r.values}
    assert len({line.key for line in CERTIFICATE_LINES}) == len(CERTIFICATE_LINES)
    assert {line.key for line in CERTIFICATE_LINES} <= catalog_keys

    root = tmp_path / "app"
    sites = root / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(
        json.dumps({"schema": "ablageorte/1", "sites": {"Belege": str(site)}}), encoding="utf-8"
    )
    app = make_app(4711, root, user=USER)
    page = page_client(app).get("/arbeit?jahr=2025").text
    section = page.split("<h2>Lohnsteuerbescheinigung</h2>", 1)[1].split("</section>", 1)[0]
    for line in CERTIFICATE_LINES:
        assert f"{line.overview_label}:" in section
