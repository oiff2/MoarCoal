"""Tests: Dokumentart Beitragsbescheinigung Kranken-/Pflegeversicherung (eDaten `VaSt_KRV`)
einlesen, Werte `provision.*` und VOR Z. 23 bis 25 (nur tmp_path, erfundene Daten)."""

import datetime
import html
import re
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
    change_document,
    duplicate_findings,
    take_in,
)
from moarcoal.modules import MODULES
from moarcoal.modules.provision import (
    HEALTH_CONTRIBUTION_CERTIFICATE,
    REGISTRATION,
    HealthContributionCertificate,
)
from moarcoal.modules.provision.health_certificate.entries import (
    Characteristic,
    ContributionKind,
)
from moarcoal.modules.provision.health_certificate.reading import (
    READER_VERSION,
    contribution_kind,
    read_in_health_contribution_certificate,
)
from moarcoal.modules.provision.health_certificate.values import (
    CARE,
    HEALTH_BASIC,
    REFUNDS,
    STATUTORY_REFUNDS,
    STATUTORY_REFUNDS_NO_SICK_PAY,
)
from moarcoal.modules.tax_year.anlage_vor import (
    VOR_PRIVATE_CARE,
    VOR_PRIVATE_HEALTH,
    VOR_PRIVATE_REFUNDS,
    VOR_STATUTORY_REFUNDS,
)
from moarcoal.registration import open_module_store
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Delete,
    Document,
    Entry,
    EntryAddress,
    Issuer,
    Put,
    Rejected,
    Store,
    entry_checksum,
)
from moarcoal.values.model import Amount, ExposedValue, NotYetComputable, Period
from moarcoal.values.testing import evaluate

USER = "anna"
YEAR = Period.year(2025)
KINDS = {k.key: k for r in MODULES for k in r.document_kinds}
KEY = HEALTH_CONTRIBUTION_CERTIFICATE.key

HEALTH = (
    "Geleistete Beiträge zur Krankenversicherung (ohne Krankengeldanspruch) "
    "ohne Zusatzbeitrag für Basisleistungen"
)
CARE_ART = "Geleistete Beiträge zur sozialen oder privaten Pflegepflichtversicherung"
REFUND = (
    "Erstattete Beiträge zur Krankenversicherung (ohne Krankengeldanspruch) "
    "ohne Zusatzbeitrag für Basisleistungen"
)
PRIVATE, STATUTORY = "privat", "gesetzlich"
PREFIX = "id-VaSt_KRV-Vertragsdaten-Beitragsdaten"
UNKNOWN_ROW = "".join(
    [
        "<tr><th>?</th><td>",
        '<span data-name="id-VaSt_KRV-Neu-Feld_usb1_1-1">',
        "<span>x</span></span></td></tr>",
    ]
)


def block(
    n: int,
    art: str,
    amount: str,
    merkmal: str = PRIVATE,
    start: str | None = "",
    end: str | None = "",
    currency: str | None = "EUR",
    year: int = 2025,
) -> str:
    """Ein Block `Vertragsdaten-Beitragsdaten` mit dem Index `_usb1_1-1-<n>-1`."""
    start = f"01.01.{year}" if start == "" else start
    end = f"31.12.{year}" if end == "" else end
    cells = [
        ("MerkmalBeiTrag", "Merkmal", merkmal),
        ("BetragArt", "Art", art),
        ("Beginn", "Beginn", start),
        ("Ende", "Ende", end),
        ("Waehrung", "Währung", currency),
        ("Betrag", "Betrag", amount),
    ]
    return "\n".join(
        f'<tr><th>{label}</th><td><span data-name="{PREFIX}-{name}_usb1_1-1-{n}-1">'
        f"<span>{html.escape(text)}</span></span></td></tr>"
        for name, label, text in cells
        if text is not None
    )


def certificate(*blocks: str, extra: str = "", year: int = 2025) -> str:
    return (
        "<!DOCTYPE html><html><head><title>Synthetische Beitragsbescheinigung</title></head><body>"
        f"<!-- Belegart: VaSt_KRV -->\n<!-- Belegversion: {year}01 -->\n"
        f"<!-- Veranlagungsjahr: {year} -->\n<table><tbody>\n"
        + "\n".join(blocks)
        + extra
        + "\n</tbody></table></body></html>"
    )


def standard() -> str:
    """Zwei Blöcke Basis-KV (summiert), Pflege, Erstattung und ein gesetzlicher Block."""
    return certificate(
        block(1, HEALTH, "1.200,40"),
        block(2, HEALTH, "100,30"),
        block(3, CARE_ART, "300,05"),
        block(4, REFUND, "50,99"),
        block(5, HEALTH, "999,99", merkmal=STATUTORY),
    )


def make_document(issuer: EntryAddress | None = None, year: int | None = 2025) -> Document:
    return Document(
        owner=USER,
        site="Belege",
        path="krv.html",
        sha256="0" * 64,
        document_kind=KEY,
        issuer=issuer,
        period_start=datetime.date(year, 1, 1) if year else None,
        period_end=datetime.date(year, 12, 31) if year else None,
    )


def read(content: str | bytes, year: int | None = 2025) -> HealthContributionCertificate:
    data = content.encode() if isinstance(content, str) else content
    (entry,) = read_in_health_contribution_certificate(make_document(year=year), data)
    assert isinstance(entry, HealthContributionCertificate)
    return entry


# --- Einlese-Regel ---------------------------------------------------------------------------


def test_every_block_is_a_line_with_its_cents_and_place() -> None:
    entry = read(standard())

    assert entry.year == 2025 and entry.reader_version == READER_VERSION
    assert [(line.kind, line.cents) for line in entry.lines] == [
        (ContributionKind.HEALTH_BASIC, 120_040),
        (ContributionKind.HEALTH_BASIC, 10_030),
        (ContributionKind.CARE, 30_005),
        (ContributionKind.HEALTH_REFUND, 5_099),
        (ContributionKind.HEALTH_BASIC, 99_999),
    ]
    first = entry.lines[0]
    assert first.place == f"{PREFIX}-Betrag_usb1_1-1-1-1"
    assert first.characteristic is Characteristic.PRIVATE and first.art == HEALTH
    assert (first.start, first.end) == (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))
    assert entry.lines[4].characteristic is Characteristic.STATUTORY
    assert entry.unrecognized == []


def test_unexpected_format_names_the_document_kind() -> None:
    with pytest.raises(ReadInError, match=r"sieht nach einem PDF aus\).*Beitragsbescheinigung"):
        read(b"%PDF-1.7\n1 0 obj")
    with pytest.raises(ReadInError, match="Dokumentart Beitragsbescheinigung"):
        read("<!-- Belegart: VaSt_LStB --><p>x</p>")


def test_a_file_without_contribution_blocks_is_rejected() -> None:
    with pytest.raises(ReadInError, match="keine Beitragsdaten"):
        read(certificate())


def test_wrong_year_and_missing_period_are_rejected() -> None:
    with pytest.raises(ReadInError, match="Steuerjahr 2025"):
        read(standard(), year=2024)
    with pytest.raises(ReadInError, match="keinen Bezugszeitraum"):
        read(standard(), year=None)


def test_a_block_outside_the_year_is_rejected_not_counted() -> None:
    late = certificate(block(1, HEALTH, "10,00", end="31.12.2026"))
    with pytest.raises(ReadInError, match="liegt nicht im Jahr 2025"):
        read(late)


@pytest.mark.parametrize("missing", ["MerkmalBeiTrag", "BetragArt", "Betrag"])
def test_a_block_without_a_required_field_is_rejected(missing: str) -> None:
    text = standard()
    lines = [r for r in text.splitlines() if f"-{missing}_usb1_1-1-2-1" not in r]
    with pytest.raises(ReadInError, match=f"Beitragsdaten 2:.*{missing}"):
        read("\n".join(lines))


def test_other_currency_and_inexact_amount_are_rejected() -> None:
    with pytest.raises(ReadInError, match="nur Euro"):
        read(certificate(block(1, HEALTH, "10,00", currency="USD")))
    with pytest.raises(ReadInError, match="kein Betrag"):
        read(certificate(block(1, HEALTH, "10,005")))


def test_a_repeated_field_in_one_block_is_not_guessed() -> None:
    twice = block(1, HEALTH, "10,00") + "\n" + block(1, HEALTH, "20,00")
    with pytest.raises(ReadInError, match="mehrfach im selben Block"):
        read(certificate(twice))


def test_unknown_art_and_merkmal_are_kept_not_dropped() -> None:
    entry = read(
        certificate(
            block(1, "Etwas ganz anderes", "5,00"),
            block(2, HEALTH, "7,00", merkmal="gemischt"),
        )
    )

    assert entry.lines[0].kind is None and entry.lines[0].art == "Etwas ganz anderes"
    assert entry.lines[1].characteristic is None and entry.lines[1].merkmal == "gemischt"


def test_unknown_paths_are_kept_as_unrecognized() -> None:
    extra = UNKNOWN_ROW
    entry = read(certificate(block(1, HEALTH, "1,00"), extra=extra))

    assert entry.unrecognized == ["Neu-Feld"]


def test_refunds_are_known_by_their_prefix_only_for_health() -> None:
    assert contribution_kind(REFUND) is ContributionKind.HEALTH_REFUND
    assert contribution_kind("Erstattete Beiträge zur Krankenversicherung  (anders)") is (
        ContributionKind.HEALTH_REFUND
    )
    assert contribution_kind("  " + HEALTH.replace(" ", "  ")) is ContributionKind.HEALTH_BASIC
    assert contribution_kind("Beiträge zur Krankenversicherung") is None


# --- im Betrieb: aufnehmen, Eindeutigkeit, Werte, VOR ------------------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "ablage"
    folder.mkdir()
    (folder / "krv.html").write_text(standard(), encoding="utf-8")
    return folder


@pytest.fixture
def store(tmp_path: Path, site: Path) -> Store:
    sites = tmp_path / "daten" / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(f'{{"schema": "ablageorte/1", "sites": {{"Belege": "{site}"}}}}')
    return open_module_store(tmp_path / "daten", MODULES)


def add_issuer(store: Store, name: str) -> EntryAddress:
    issuer = Issuer(owner=COMMON_OWNER, name=name)
    assert isinstance(store.apply([Put(issuer)]), Applied)
    return issuer.address


def write(site: Path, name: str, content: str) -> None:
    (site / name).write_text(content, encoding="utf-8")


def take(
    store: Store, path: str = "krv.html", issuer: EntryAddress | None = None, year: int = 2025
) -> TakenIn | IntakeRejected:
    return take_in(store, KINDS, USER, "Belege", path, KEY, year, issuer=issuer)


def entries(store: Store) -> list[Entry]:
    return list(store.state().entries.values())


def get(store: Store, key: str) -> ExposedValue | NotYetComputable:
    result = evaluate(MODULES, entries(store)).get(key, USER, YEAR)
    assert isinstance(result, ExposedValue | NotYetComputable), result
    return result


def test_take_in_stores_document_and_reading(store: Store) -> None:
    taken = take(store)

    assert isinstance(taken, TakenIn)
    (entry,) = taken.entries
    assert isinstance(entry, HealthContributionCertificate)
    assert entry.document == taken.document.address and len(entry.lines) == 5


def test_a_second_certificate_of_the_same_issuer_and_year_is_rejected_another_issuer_is_not(
    store: Store, site: Path
) -> None:
    alpha, beta = add_issuer(store, "Alpha Krankenversicherung"), add_issuer(store, "Beta Kasse")
    write(site, "zweite.html", standard() + "<!-- 2 -->")
    write(site, "dritte.html", standard() + "<!-- 3 -->")
    write(site, "vorjahr.html", certificate(block(1, CARE_ART, "1,00", year=2024), year=2024))
    first = take(store, issuer=alpha)
    assert isinstance(first, TakenIn)

    second = take(store, "zweite.html", issuer=alpha)
    other = take(store, "dritte.html", issuer=beta)
    other_year = take(store, "vorjahr.html", issuer=alpha, year=2024)

    assert isinstance(second, IntakeRejected)
    assert second.reasons == (f"Existiert bereits: {HEALTH_CONTRIBUTION_CERTIFICATE.title} 2025",)
    assert second.existing == first.document
    assert isinstance(other, TakenIn)
    assert isinstance(other_year, TakenIn)


def test_without_issuer_two_certificates_of_a_year_clash(store: Store, site: Path) -> None:
    write(site, "zweite.html", standard() + "<!-- 2 -->")
    assert isinstance(take(store), TakenIn)

    assert isinstance(take(store, "zweite.html"), IntakeRejected)


def test_changing_issuer_or_year_into_a_clash_is_rejected_by_the_write_path(
    store: Store, site: Path
) -> None:
    alpha, beta = add_issuer(store, "Alpha Krankenversicherung"), add_issuer(store, "Beta Kasse")
    write(site, "beta.html", standard() + "<!-- 2 -->")
    write(site, "vorjahr.html", certificate(block(1, CARE_ART, "1,00", year=2024), year=2024))
    first, second = take(store, issuer=alpha), take(store, "beta.html", issuer=beta)
    older = take(store, "vorjahr.html", issuer=alpha, year=2024)
    assert isinstance(first, TakenIn) and isinstance(second, TakenIn)
    assert isinstance(older, TakenIn)

    by_issuer = change_document(store, KINDS, second.document, alpha)
    by_year = store.apply(
        [
            Put(
                older.document.model_copy(
                    update={
                        "period_start": datetime.date(2025, 1, 1),
                        "period_end": datetime.date(2025, 12, 31),
                    }
                ),
                expected=entry_checksum(older.document),
            )
        ]
    )

    assert isinstance(by_issuer, IntakeRejected) and by_issuer.existing == first.document
    assert isinstance(by_year, Rejected)
    assert duplicate_findings(store.state(), USER, KINDS) == []


def test_values_sum_the_private_blocks_unrounded_with_items_and_places(store: Store) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)

    health, care, refunds = (get(store, key) for key in (HEALTH_BASIC, CARE, REFUNDS))

    assert isinstance(health, ExposedValue)
    assert health.amount == Amount.eur_cents(130_070)  # 1.200,40 + 100,30; gesetzlich zählt nicht
    assert [i.amount.value for i in health.items] == [Decimal("1200.40"), Decimal("100.30")]
    assert all(i.locator.entry_address == taken.document.address for i in health.items)
    assert isinstance(care, ExposedValue) and care.amount == Amount.eur_cents(30_005)
    assert isinstance(refunds, ExposedValue) and refunds.amount == Amount.eur_cents(5_099)


def test_vor_fields_round_only_at_the_field_in_the_direction_of_the_field(store: Store) -> None:
    assert isinstance(take(store), TakenIn)

    def field(key: str) -> Amount:
        result = get(store, key)
        assert isinstance(result, ExposedValue), result
        return result.amount

    assert field(VOR_PRIVATE_HEALTH) == Amount.eur_cents(130_100)  # Ausgabe: 1.300,70 -> 1.301
    assert field(VOR_PRIVATE_CARE) == Amount.eur_cents(30_100)  # Ausgabe: 300,05 -> 301
    assert field(VOR_PRIVATE_REFUNDS) == Amount.eur_cents(5_000)  # Einnahme: 50,99 -> 50


def test_without_certificate_the_values_are_not_yet_computable_never_zero(store: Store) -> None:
    for key in (
        HEALTH_BASIC,
        CARE,
        REFUNDS,
        VOR_PRIVATE_HEALTH,
        VOR_PRIVATE_CARE,
        VOR_PRIVATE_REFUNDS,
    ):
        result = get(store, key)
        assert isinstance(result, NotYetComputable)
        assert "Beitragsbescheinigung" in str(result)


def test_a_missing_basic_amount_is_not_zero_but_no_refund_is_zero_with_the_decision(
    store: Store, site: Path
) -> None:
    write(site, "nur_pflege.html", certificate(block(1, CARE_ART, "10,00")))
    assert isinstance(take(store, "nur_pflege.html"), TakenIn)

    health, refunds = get(store, HEALTH_BASIC), get(store, REFUNDS)

    assert isinstance(health, NotYetComputable)
    assert isinstance(refunds, ExposedValue) and refunds.amount == Amount.eur_cents(0)
    assert refunds.items == ()
    assert any(s.kind == "decision" and "0 €" in s.text for s in refunds.workings.steps)


def test_an_unknown_art_makes_all_values_not_yet_computable_and_names_it(
    store: Store, site: Path
) -> None:
    write(
        site, "neu.html", certificate(block(1, HEALTH, "1,00"), block(2, "Sonderbeitrag X", "2,00"))
    )
    assert isinstance(take(store, "neu.html"), TakenIn)

    for key in (HEALTH_BASIC, CARE, REFUNDS, VOR_PRIVATE_HEALTH):
        result = get(store, key)
        assert isinstance(result, NotYetComputable)
        assert "Sonderbeitrag X" in str(result)


def test_an_unknown_art_in_a_statutory_block_does_not_matter(store: Store, site: Path) -> None:
    content = certificate(
        block(1, HEALTH, "1,00"), block(2, "Sonderbeitrag X", "2,00", merkmal=STATUTORY)
    )
    write(site, "gesetzlich.html", content)
    assert isinstance(take(store, "gesetzlich.html"), TakenIn)

    assert isinstance(get(store, HEALTH_BASIC), ExposedValue)


def test_an_unknown_merkmal_and_an_unknown_path_make_the_values_not_yet_computable(
    store: Store, site: Path
) -> None:
    write(site, "merkmal.html", certificate(block(1, HEALTH, "1,00", merkmal="gemischt")))
    assert isinstance(take(store, "merkmal.html"), TakenIn)
    result = get(store, HEALTH_BASIC)
    assert isinstance(result, NotYetComputable) and "gemischt" in str(result)


def test_an_unrecognized_path_makes_the_values_not_yet_computable_and_names_it(
    store: Store, site: Path
) -> None:
    extra = UNKNOWN_ROW
    write(site, "pfad.html", certificate(block(1, HEALTH, "1,00"), extra=extra))
    assert isinstance(take(store, "pfad.html"), TakenIn)

    result = get(store, HEALTH_BASIC)
    assert isinstance(result, NotYetComputable) and "Neu-Feld" in str(result)


def test_an_older_reading_makes_the_values_not_yet_computable(store: Store) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)
    (entry,) = taken.entries
    assert isinstance(entry, HealthContributionCertificate)
    old = entry.model_copy(update={"reader_version": READER_VERSION - 1})
    values = evaluate(MODULES, [*[e for e in entries(store) if e.address != entry.address], old])

    result = values.get(HEALTH_BASIC, USER, YEAR)

    assert isinstance(result, NotYetComputable) and "älteren Einlese-Regel" in str(result)


def test_values_sum_over_all_certificates_of_the_year_and_not_of_other_years(
    store: Store, site: Path
) -> None:
    alpha, beta = add_issuer(store, "Alpha Krankenversicherung"), add_issuer(store, "Beta Kasse")
    write(site, "beta.html", certificate(block(1, HEALTH, "10,00"), block(2, CARE_ART, "1,00")))
    write(site, "alt.html", certificate(block(1, HEALTH, "777,00", year=2024), year=2024))
    assert isinstance(take(store, issuer=alpha), TakenIn)
    assert isinstance(take(store, "beta.html", issuer=beta), TakenIn)
    assert isinstance(take(store, "alt.html", issuer=alpha, year=2024), TakenIn)

    health = get(store, HEALTH_BASIC)

    assert isinstance(health, ExposedValue) and health.amount == Amount.eur_cents(131_070)


def test_deleting_the_document_takes_the_certificate_along(store: Store) -> None:
    taken = take(store)
    assert isinstance(taken, TakenIn)

    deleted = store.apply([Delete(taken.document.address, entry_checksum(taken.document))])

    assert isinstance(deleted, Applied)
    assert store.state().of_kind(HealthContributionCertificate) == []
    assert isinstance(take(store), TakenIn)


# --- Seite Vorsorge ---------------------------------------------------------------------------

PORT = 4711


def client_of(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_the_page_shows_the_certificates_assigned_to_the_agreement_of_the_issuer_or_without(
    tmp_path: Path,
) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    write(site, "alpha.html", standard())
    write(site, "beta.html", certificate(block(1, HEALTH, "42,00")))
    sites = tmp_path / "common" / "sites.json"
    sites.parent.mkdir(parents=True)
    sites.write_text(f'{{"schema": "ablageorte/1", "sites": {{"Belege": "{site}"}}}}')
    app = make_app(PORT, tmp_path, user=USER)
    store: Store = app.state.store
    alpha, beta = add_issuer(store, "Alpha Krankenversicherung"), add_issuer(store, "Beta Kasse")
    agreement = Agreement(owner=USER, issuer=alpha, name="Krankenvollversicherung")
    assert isinstance(store.apply([Put(agreement)]), Applied)
    assert isinstance(take(store, "alpha.html", issuer=alpha), TakenIn)
    assert isinstance(take(store, "beta.html", issuer=beta), TakenIn)
    client = client_of(app)

    page = client.get("/vorsorge?jahr=2025")

    assert page.status_code == 200
    text = html.unescape(page.text)
    section = text[text.index('id="vorsorge-bescheinigungen"') :]
    assert "1.200,40 €" in section and "42,00 €" in section
    assert re.search(r"Krankenvollversicherung</a>", section)
    assert "ohne Vertrag" in section
    assert "999,99 €" in section and "gesetzlich" in section
    empty = client.get("/vorsorge?jahr=2024")
    assert "keine Beitragsbescheinigung eingelesen" in empty.text


def test_the_registration_lists_the_new_kind_and_values() -> None:
    assert HEALTH_CONTRIBUTION_CERTIFICATE in REGISTRATION.document_kinds
    assert {d.entry.key for d in REGISTRATION.values} == {
        HEALTH_BASIC,
        CARE,
        REFUNDS,
        "provision.private_health_extra",
        "provision.unemployment_contributions",
        "provision.disability_contributions",
        "provision.accident_liability_risk_contributions",
        STATUTORY_REFUNDS,
        STATUTORY_REFUNDS_NO_SICK_PAY,
    }
    assert HEALTH_CONTRIBUTION_CERTIFICATE.unique_per_issuer


# --- VOR Z. 14 und 15: gesetzlich erstattete Beiträge, 0 € nur mit Begründung -------------------

CARE_REFUND_ART = "Erstattete Beiträge zur sozialen oder privaten Pflegepflichtversicherung"
STATUTORY_KEYS = (STATUTORY_REFUNDS, STATUTORY_REFUNDS_NO_SICK_PAY, VOR_STATUTORY_REFUNDS)


def decisions(result: ExposedValue) -> list[str]:
    return [s.text for s in result.workings.steps if s.kind == "decision"]


def test_statutory_refunds_sum_the_statutory_blocks_only_rounded_at_the_field(
    store: Store, site: Path
) -> None:
    content = certificate(
        block(1, REFUND, "10,90", merkmal=STATUTORY),
        block(2, CARE_REFUND_ART, "5,20", merkmal=STATUTORY),
        block(3, REFUND, "50,99"),  # privat zählt nicht
        block(4, HEALTH, "700,00", merkmal=STATUTORY),  # Beitrag, keine Erstattung
    )
    write(site, "gesetzlich.html", content)
    assert isinstance(take(store, "gesetzlich.html"), TakenIn)

    z14, z15 = get(store, STATUTORY_REFUNDS), get(store, STATUTORY_REFUNDS_NO_SICK_PAY)
    assert isinstance(z14, ExposedValue) and z14.amount == Amount.eur_cents(1_610)
    assert [i.amount.value for i in z14.items] == [Decimal("10.90"), Decimal("5.20")]
    assert isinstance(z15, ExposedValue) and z15.amount == Amount.eur_cents(1_610)
    field = get(store, VOR_STATUTORY_REFUNDS)
    assert isinstance(field, ExposedValue) and field.amount == Amount.eur_cents(
        1_600
    )  # 16,10 -> 16


def test_line_15_leaves_a_health_refund_open_that_is_not_known_to_be_without_sick_pay(
    store: Store, site: Path
) -> None:
    other = "Erstattete Beiträge zur Krankenversicherung (anders)"
    write(site, "anders.html", certificate(block(1, other, "10,00", merkmal=STATUTORY)))
    assert isinstance(take(store, "anders.html"), TakenIn)

    assert isinstance(get(store, STATUTORY_REFUNDS), ExposedValue)  # Z. 14 nimmt jede Erstattung
    result = get(store, STATUTORY_REFUNDS_NO_SICK_PAY)
    assert isinstance(result, NotYetComputable) and "(anders)" in str(result)


def test_a_statutory_block_without_a_refund_makes_lines_14_and_15_zero_with_a_decision(
    store: Store,
) -> None:
    assert isinstance(take(store), TakenIn)  # standard(): ein gesetzlicher Block, aber Beitrag

    for key in STATUTORY_KEYS[:2]:
        result = get(store, key)
        assert isinstance(result, ExposedValue) and result.amount == Amount.eur_cents(0)
        assert result.items == ()
        assert any("0 €" in text for text in decisions(result))


def test_a_purely_private_year_is_zero_with_the_reason_only_private(
    store: Store, site: Path
) -> None:
    write(site, "privat.html", certificate(block(1, HEALTH, "1,00"), block(2, REFUND, "2,00")))
    assert isinstance(take(store, "privat.html"), TakenIn)

    for key in STATUTORY_KEYS:
        result = get(store, key)
        assert isinstance(result, ExposedValue) and result.amount == Amount.eur_cents(0)
    z14 = get(store, STATUTORY_REFUNDS)
    assert isinstance(z14, ExposedValue)
    assert any("alle Beitragsbescheinigungen 2025 sind privat" in t for t in decisions(z14))


def test_statutory_blocks_without_refunds_are_zero_with_their_own_reason(
    store: Store, site: Path
) -> None:
    write(site, "gesetzlich.html", certificate(block(1, HEALTH, "1,00", merkmal=STATUTORY)))
    assert isinstance(take(store, "gesetzlich.html"), TakenIn)

    z14 = get(store, STATUTORY_REFUNDS)
    assert isinstance(z14, ExposedValue) and z14.amount == Amount.eur_cents(0)
    assert any("gesetzlichen Versicherung: 0 €" in t for t in decisions(z14))


def test_without_certificate_lines_14_and_15_are_not_yet_computable_and_say_it_is_missing(
    store: Store,
) -> None:
    for key in STATUTORY_KEYS:
        result = get(store, key)
        assert isinstance(result, NotYetComputable)
        assert "keine Beitragsbescheinigung Kranken-/Pflegeversicherung aufgenommen" in str(result)


UNKNOWN_CASES = {
    "art": (certificate(block(1, "Sonderbeitrag X", "2,00", merkmal=STATUTORY)), "X"),
    "merkmal": (certificate(block(1, REFUND, "1,00", merkmal="gemischt")), "gemischt"),
    "pfad": (
        certificate(block(1, REFUND, "1,00", merkmal=STATUTORY), extra=UNKNOWN_ROW),
        "Neu-Feld",
    ),
}


@pytest.mark.parametrize("case", UNKNOWN_CASES)
def test_an_unknown_art_merkmal_or_path_makes_lines_14_and_15_not_yet_computable(
    store: Store, site: Path, case: str
) -> None:
    content, needle = UNKNOWN_CASES[case]
    write(site, "neu.html", content)
    assert isinstance(take(store, "neu.html"), TakenIn)

    for key in STATUTORY_KEYS:
        result = get(store, key)
        assert isinstance(result, NotYetComputable) and needle in str(result)
