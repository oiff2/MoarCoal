"""Tests: Dokumentart Lohnsteuerbescheinigung (eDaten) einlesen, Felder 4 bis 7 (nur tmp_path)."""

import datetime
import re
import shutil
from pathlib import Path

import pytest

from moarcoal.documents import IntakeRejected, ReadInError, TakenIn, take_in
from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading
from moarcoal.modules.tax_year.anlage_n import (
    N_GROSS_WAGES,
    N_GROSS_WAGES_SINGLE,
    N_INCOME_TAX,
    N_SOLI,
    N_TAX_CLASS,
)
from moarcoal.modules.tax_year.comparison import DEVIATION, MISSING
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work import WAGE_TAX_CERTIFICATE, WageTaxCertificate
from moarcoal.modules.work.reading import read_in_wage_tax_certificate
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
    with pytest.raises(ReadInError, match="keine Lohnsteuerbescheinigung"):
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
    assert set(entry.places) == {"tax_class", "gross_wages", "income_tax", "soli"}


def test_wrong_year_is_rejected() -> None:
    with pytest.raises(ReadInError, match="Steuerjahr 2025"):
        read(year=2024)


def test_other_belegart_is_rejected() -> None:
    with pytest.raises(ReadInError, match="keine Lohnsteuerbescheinigung"):
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
    for key in FIELDS_4_TO_7:
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
    keys = {str(k) for k in FIELDS_4_TO_7} | {str(N_GROSS_WAGES_SINGLE)}
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
}


def test_protocol_is_compared_against_the_computed_fields(store: Store) -> None:
    assert comparison(store, MATCHING) == set()


def test_deviating_protocol_gives_a_finding(store: Store) -> None:
    found = comparison(store, {**MATCHING, "E0200301": "6.500,00"})
    assert found == {(DEVIATION, str(N_INCOME_TAX))}
