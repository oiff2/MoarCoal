"""Tests: Dokumentart Anbieterbescheinigung Basisrente (eDaten `VaSt_RUE`) einlesen, Eindeutigkeit
je Vertragsnummer und Jahr, Wert `provision.basic_pension` und VOR Z. 8 (nur tmp_path, erfundene
Daten, auch erfundene Vertragsnummern)."""

import datetime
import html
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal.documents import (
    IntakeRejected,
    ReadInError,
    TakenIn,
    duplicate_findings,
    read_in_again,
    take_in,
)
from moarcoal.modules import MODULES
from moarcoal.modules.provision import BASIC_PENSION_CERTIFICATE, BasicPensionCertificate
from moarcoal.modules.provision.basic_pension.reading import (
    READER_VERSION,
    read_in_basic_pension_certificate,
)
from moarcoal.modules.provision.basic_pension.values import BASIC_PENSION
from moarcoal.modules.tax_year.anlage_vor import VOR_BASIC_PENSION
from moarcoal.registration import open_module_store
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Delete,
    Document,
    Entry,
    Issuer,
    Put,
    Rereading,
    Store,
    entry_checksum,
)
from moarcoal.values.model import Amount, ExposedValue, NotYetComputable, Period
from moarcoal.values.testing import evaluate

USER = "anna"
YEAR = Period.year(2025)
KINDS = {k.key: k for r in MODULES for k in r.document_kinds}
KEY = BASIC_PENSION_CERTIFICATE.key
NUMBER = "RR-4711-0815"
OTHER_NUMBER = "RR-9999-0001"
PREFIX = "id-VaSt_RUE-Vertragsdaten"


def field(name: str, text: str, suffix: str = "") -> str:
    return (
        f'<tr><th>{name}</th><td><span data-name="{PREFIX}-{name}{suffix}">'
        f"<span>{html.escape(text)}</span></span></td></tr>"
    )


def block(n: int, paid_year: int | str | None, amount: str | None, currency: str = "EUR") -> str:
    cells = [("Zahljahr", paid_year), ("Waehrung", currency), ("Betrag", amount)]
    return "\n".join(
        field(f"Beitragsdaten-{name}", str(text), f"_usb1_1-1-{n}-1")
        for name, text in cells
        if text is not None
    )


def certificate(
    *blocks: str,
    number: str | None = NUMBER,
    certification: str | None = "ZERT-0042",
    extra: str = "",
    year: int = 2025,
) -> str:
    head = ""
    if number is not None:
        head += field("VertragsNr", number)
    if certification is not None:
        head += field("ZertifizierungsNr", certification)
    return (
        "<!DOCTYPE html><html><head><title>Synthetische Bescheinigung</title></head><body>"
        f"<!-- Belegart: VaSt_RUE -->\n<!-- Belegversion: {year}01 -->\n"
        f"<!-- Veranlagungsjahr: {year} -->\n<table><tbody>\n{head}\n"
        + "\n".join(blocks)
        + extra
        + "\n</tbody></table></body></html>"
    )


def standard(number: str = NUMBER) -> str:
    """Zwei Beitragsblöcke (summiert)."""
    return certificate(block(1, 2025, "1.200,40"), block(2, 2025, "100,30"), number=number)


def make_document(year: int | None = 2025) -> Document:
    return Document(
        owner=USER,
        site="Belege",
        path="rue.html",
        sha256="0" * 64,
        document_kind=KEY,
        period_start=datetime.date(year, 1, 1) if year else None,
        period_end=datetime.date(year, 12, 31) if year else None,
    )


def read(content: str | bytes, year: int | None = 2025) -> BasicPensionCertificate:
    data = content.encode() if isinstance(content, str) else content
    (entry,) = read_in_basic_pension_certificate(make_document(year), data)
    assert isinstance(entry, BasicPensionCertificate)
    return entry


# --- Einlese-Regel ---------------------------------------------------------------------------


def test_the_reading_holds_number_certification_and_every_block_with_its_place() -> None:
    entry = read(standard())

    assert entry.year == 2025 and entry.reader_version == READER_VERSION
    assert entry.contract_number == NUMBER and entry.certification_number == "ZERT-0042"
    assert [(line.paid_year, line.cents) for line in entry.lines] == [
        (2025, 120_040),
        (2025, 10_030),
    ]
    assert entry.lines[0].place == f"{PREFIX}-Beitragsdaten-Betrag_usb1_1-1-1-1"
    assert entry.unrecognized == []


def test_the_certification_number_is_optional_but_the_contract_number_is_not() -> None:
    assert (
        read(certificate(block(1, 2025, "1,00"), certification=None)).certification_number is None
    )
    with pytest.raises(ReadInError, match="keine Vertragsnummer"):
        read(certificate(block(1, 2025, "1,00"), number=None))
    with pytest.raises(ReadInError, match="keine Vertragsnummer"):
        read(certificate(block(1, 2025, "1,00"), number="  "))


def test_unexpected_format_names_the_document_kind() -> None:
    with pytest.raises(ReadInError, match=r"sieht nach einem PDF aus\).*Anbieterbescheinigung"):
        read(b"%PDF-1.7\n1 0 obj")
    with pytest.raises(ReadInError, match="Dokumentart Anbieterbescheinigung"):
        read("<!-- Belegart: VaSt_KRV --><p>x</p>")


def test_a_file_without_blocks_and_a_wrong_year_are_rejected() -> None:
    with pytest.raises(ReadInError, match="keine Beitragsdaten"):
        read(certificate())
    with pytest.raises(ReadInError, match="Steuerjahr 2025"):
        read(standard(), year=2024)
    with pytest.raises(ReadInError, match="keinen Bezugszeitraum"):
        read(standard(), year=None)


def test_a_paid_year_that_is_not_the_year_of_the_document_is_rejected_not_counted() -> None:
    with pytest.raises(ReadInError, match="Zahljahr „2026“ ist nicht das Jahr 2025"):
        read(certificate(block(1, 2026, "10,00")))
    with pytest.raises(ReadInError, match="Zahljahr „x“"):
        read(certificate(block(1, "x", "10,00")))


def test_a_block_without_a_required_field_other_currency_or_inexact_amount_is_rejected() -> None:
    with pytest.raises(ReadInError, match=r"Beitragsdaten 1:.*Zahljahr"):
        read(certificate(block(1, None, "10,00")))
    with pytest.raises(ReadInError, match=r"Beitragsdaten 1:.*Betrag"):
        read(certificate(block(1, 2025, None)))
    with pytest.raises(ReadInError, match="nur Euro"):
        read(certificate(block(1, 2025, "10,00", currency="USD")))
    with pytest.raises(ReadInError, match="kein Betrag"):
        read(certificate(block(1, 2025, "10,005")))


def test_a_repeated_number_and_a_repeated_field_in_one_block_are_not_guessed() -> None:
    twice = certificate(block(1, 2025, "1,00"), extra=field("VertragsNr", OTHER_NUMBER))
    with pytest.raises(ReadInError, match="Vertragsnummer steht 2-mal"):
        read(twice)
    with pytest.raises(ReadInError, match="mehrfach im selben Block"):
        read(certificate(block(1, 2025, "1,00") + "\n" + block(1, 2025, "2,00")))


def test_unknown_paths_are_kept_as_unrecognized() -> None:
    extra = field("Neu-Feld", "x", "_usb1_1-1")
    assert read(certificate(block(1, 2025, "1,00"), extra=extra)).unrecognized == [
        "Vertragsdaten-Neu-Feld"
    ]


def test_no_reading_message_names_the_contract_number() -> None:
    broken = [
        certificate(block(1, 2026, "10,00")),
        certificate(block(1, None, "10,00")),
        certificate(block(1, 2025, "10,005")),
        certificate(block(1, 2025, "1,00"), extra=field("VertragsNr", OTHER_NUMBER)),
        certificate(block(1, 2025, "10,00"), number=NUMBER + "x" * 200),
        certificate(),
    ]
    for content in broken:
        with pytest.raises(ReadInError) as raised:
            read(content)
        assert NUMBER not in str(raised.value) and OTHER_NUMBER not in str(raised.value)
        assert raised.value.__cause__ is None


# --- im Betrieb: aufnehmen, Eindeutigkeit, Werte, VOR --------------------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    folder.mkdir()
    (folder / "rue.html").write_text(standard(), encoding="utf-8")
    return folder


@pytest.fixture
def store(tmp_path: Path, site: Path) -> Store:
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(f'{{"schema": "ablageorte/1", "sites": {{"Belege": "{site}"}}}}')
    return open_module_store(tmp_path / "daten", MODULES)


def write(site: Path, name: str, content: str) -> None:
    (site / name).write_text(content, encoding="utf-8")


def take(store: Store, path: str = "rue.html", year: int = 2025) -> TakenIn | IntakeRejected:
    return take_in(store, KINDS, USER, "Belege", path, KEY, year)


def entries(store: Store) -> list[Entry]:
    return list(store.state().entries.values())


def get(store: Store, key: str) -> ExposedValue | NotYetComputable:
    result = evaluate(MODULES, entries(store)).get(key, USER, YEAR)
    assert isinstance(result, ExposedValue | NotYetComputable), result
    return result


def add_agreement(store: Store, number: str, name: str = "Basisrente Alpha") -> Agreement:
    issuer = Issuer(owner=COMMON_OWNER, name="Alpha Rentenversicherung")
    assert isinstance(store.apply([Put(issuer)]), Applied)
    agreement = Agreement(owner=USER, issuer=issuer.address, name=name, number=number)
    assert isinstance(store.apply([Put(agreement)]), Applied)
    return agreement


def test_take_in_stores_document_and_reading(store: Store) -> None:
    taken = take(store)

    assert isinstance(taken, TakenIn)
    (entry,) = taken.entries
    assert isinstance(entry, BasicPensionCertificate)
    assert entry.document == taken.document.address and len(entry.lines) == 2


def test_the_same_contract_number_and_year_is_rejected_another_number_or_year_is_not(
    store: Store, site: Path
) -> None:
    write(site, "doppelt.html", standard() + "<!-- 2 -->")
    write(site, "anders.html", standard(OTHER_NUMBER))
    write(site, "vorjahr.html", certificate(block(1, 2024, "1,00"), year=2024))
    first = take(store)
    assert isinstance(first, TakenIn)

    second = take(store, "doppelt.html")
    other_contract = take(store, "anders.html")
    other_year = take(store, "vorjahr.html", year=2024)

    assert isinstance(second, IntakeRejected)
    assert second.reasons == (f"Existiert bereits: {BASIC_PENSION_CERTIFICATE.title} 2025",)
    assert second.existing == first.document
    assert isinstance(other_contract, TakenIn)
    assert isinstance(other_year, TakenIn)


def test_case_and_whitespace_of_the_number_do_not_make_a_second_contract(
    store: Store, site: Path
) -> None:
    write(site, "gross.html", standard(NUMBER.lower().replace("-", " - ")))
    assert isinstance(take(store), TakenIn)

    assert isinstance(take(store, "gross.html"), IntakeRejected)


def test_no_rejection_or_finding_names_the_contract_number(store: Store, site: Path) -> None:
    write(site, "doppelt.html", standard() + "<!-- 2 -->")
    assert isinstance(take(store), TakenIn)
    second = take(store, "doppelt.html")
    assert isinstance(second, IntakeRejected)

    assert all(NUMBER not in reason for reason in second.reasons)
    assert all(NUMBER not in f.message for f in duplicate_findings(store.state(), USER, KINDS))


def test_changing_the_year_into_a_clash_is_rejected_by_the_write_path(
    store: Store, site: Path
) -> None:
    write(site, "vorjahr.html", certificate(block(1, 2024, "1,00"), year=2024))
    first, older = take(store), take(store, "vorjahr.html", year=2024)
    assert isinstance(first, TakenIn) and isinstance(older, TakenIn)
    # die Bescheinigung des Vorjahrs trägt dieselbe Nummer: im selben Jahr wäre sie die zweite
    moved = older.document.model_copy(
        update={
            "period_start": datetime.date(2025, 1, 1),
            "period_end": datetime.date(2025, 12, 31),
        }
    )

    result = store.apply([Put(moved, expected=entry_checksum(older.document))])

    assert not isinstance(result, Applied)
    assert all(NUMBER not in reason for reason in result.reasons.values())
    assert duplicate_findings(store.state(), USER, KINDS) == []


def test_the_value_sums_all_certificates_of_the_year_unrounded_with_places(
    store: Store, site: Path
) -> None:
    write(site, "anders.html", certificate(block(1, 2025, "10,00"), number=OTHER_NUMBER))
    write(site, "alt.html", certificate(block(1, 2024, "777,00"), year=2024))
    first, second = take(store), take(store, "anders.html")
    assert isinstance(first, TakenIn) and isinstance(take(store, "alt.html", year=2024), TakenIn)
    assert isinstance(second, TakenIn)

    result = get(store, BASIC_PENSION)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.eur_cents(131_070)  # 1.200,40 + 100,30 + 10,00
    assert [i.amount.value for i in result.items] == [
        Decimal("1200.40"),
        Decimal("100.30"),
        Decimal("10.00"),
    ]
    assert {i.locator.entry_address for i in result.items} == {
        first.document.address,
        second.document.address,
    }


def test_the_value_never_names_the_contract_number(store: Store) -> None:
    assert isinstance(take(store), TakenIn)
    result = get(store, BASIC_PENSION)
    assert isinstance(result, ExposedValue)

    text = repr(result)

    assert NUMBER not in text


def test_vor_line_8_rounds_up_only_at_the_field(store: Store) -> None:
    assert isinstance(take(store), TakenIn)

    result = get(store, VOR_BASIC_PENSION)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.eur_cents(130_100)  # Ausgabe: 1.300,70 -> 1.301


def test_the_value_counts_without_an_agreement_and_does_not_depend_on_one(
    store: Store, site: Path
) -> None:
    assert isinstance(take(store), TakenIn)
    without = get(store, BASIC_PENSION)
    add_agreement(store, NUMBER)
    assert get(store, BASIC_PENSION) == without


def test_without_certificate_the_value_and_line_8_are_not_yet_computable_never_zero(
    store: Store,
) -> None:
    for key in (BASIC_PENSION, VOR_BASIC_PENSION):
        result = get(store, key)
        assert isinstance(result, NotYetComputable)
        assert "Anbieterbescheinigung Basisrente" in str(result)


def test_an_unrecognized_path_makes_the_value_not_yet_computable_and_names_it(
    store: Store, site: Path
) -> None:
    extra = field("Neu-Feld", "x", "_usb1_1-1")
    write(site, "pfad.html", certificate(block(1, 2025, "1,00"), extra=extra))
    assert isinstance(take(store, "pfad.html"), TakenIn)

    result = get(store, BASIC_PENSION)

    assert isinstance(result, NotYetComputable) and "Neu-Feld" in str(result)
    assert isinstance(get(store, VOR_BASIC_PENSION), NotYetComputable)


def test_an_older_reading_makes_the_value_not_yet_computable(store: Store) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)
    (entry,) = taken.entries
    old = entry.model_copy(update={"reader_version": READER_VERSION - 1})
    values = evaluate(MODULES, [*[e for e in entries(store) if e.address != entry.address], old])

    result = values.get(BASIC_PENSION, USER, YEAR)

    assert isinstance(result, NotYetComputable) and "älteren Einlese-Regel" in str(result)


def test_deleting_the_document_takes_the_certificate_along_and_frees_the_number(
    store: Store, site: Path
) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)

    deleted = store.apply([Delete(taken.document.address, entry_checksum(taken.document))])

    assert isinstance(deleted, Applied)
    assert store.state().of_kind(BasicPensionCertificate) == []
    assert isinstance(take(store), TakenIn)


# --- Vertragsnummer ist sensibel -------------------------------------------------------------


def test_the_contract_number_goes_into_the_derived_denylist(store: Store, tmp_path: Path) -> None:
    assert isinstance(take(store), TakenIn)

    denylist = (tmp_path / "daten" / "common" / "derived-denylist.txt").read_text(encoding="utf-8")

    assert NUMBER in denylist.splitlines()


def test_rereading_does_not_keep_or_show_a_changed_contract_number(
    store: Store, site: Path
) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)

    def changed(document: Document, content: bytes) -> list[BasicPensionCertificate]:
        (entry,) = read_in_basic_pension_certificate(document, content)
        assert isinstance(entry, BasicPensionCertificate)
        return [
            entry.model_copy(
                update={
                    "reader_version": READER_VERSION + 1,
                    "contract_number": OTHER_NUMBER,
                    "certification_number": "ZERT-0043",
                }
            )
        ]

    newer = replace(BASIC_PENSION_CERTIFICATE, read_in=changed, reader_version=READER_VERSION + 1)
    read_in_again(store, {KEY: newer})

    (rereading,) = store.state().of_kind(Rereading)
    shown = {d.location: (d.before, d.after) for d in rereading.differences}
    number = shown["BasicPensionCertificate.contract_number"]
    assert NUMBER not in str(number) and OTHER_NUMBER not in str(number)
    assert None not in number  # es steht fest, dass sich die Nummer geändert hat
    assert shown["BasicPensionCertificate.certification_number"] == ("ZERT-0042", "ZERT-0043")
    assert NUMBER not in repr(rereading) and OTHER_NUMBER not in repr(rereading)


# --- Seite Vorsorge ---------------------------------------------------------------------------

PORT = 4711


def client_of(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_the_page_shows_the_certificate_at_the_agreement_with_the_same_number_or_without(
    tmp_path: Path,
) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    write(site, "alpha.html", standard())
    write(site, "beta.html", certificate(block(1, 2025, "42,00"), number=OTHER_NUMBER))
    sites = tmp_path / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(f'{{"schema": "ablageorte/1", "sites": {{"Belege": "{site}"}}}}')
    app = make_app(PORT, tmp_path, user=USER)
    store: Store = app.state.store
    add_agreement(store, f" {NUMBER.lower()} ")
    assert isinstance(take(store, "alpha.html"), TakenIn)
    assert isinstance(take(store, "beta.html"), TakenIn)
    client = client_of(app)

    page = client.get("/vorsorge?jahr=2025")

    assert page.status_code == 200
    text = html.unescape(page.text)
    section = text[text.index('id="vorsorge-basisrente"') :]
    assert "1.200,40 €" in section and "42,00 €" in section
    assert "Basisrente Alpha</a>" in section and "ohne Vertrag" in section
    assert NUMBER in section and OTHER_NUMBER in section
    empty = client.get("/vorsorge?jahr=2024")
    assert "keine Anbieterbescheinigung Basisrente eingelesen" in empty.text


def test_the_registration_lists_the_kind_with_a_unique_key_not_the_issuer_flag() -> None:
    assert BASIC_PENSION_CERTIFICATE in KINDS.values()
    assert BASIC_PENSION_CERTIFICATE.unique_per_period
    assert BASIC_PENSION_CERTIFICATE.unique_by is not None
    first = make_document()
    # ohne Einlesung kollidiert das Dokument mit keinem anderen
    assert BASIC_PENSION_CERTIFICATE.unique_by(first, {}) == first.address
