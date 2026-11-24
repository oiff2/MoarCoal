"""Tests: Befunde des Moduls Vorsorge (Bescheinigung ohne Vertrag, Vertrag ohne Bescheinigung) und
Vertrag aus der Bescheinigung anlegen (nur tmp_path, erfundene Daten und Vertragsnummern)."""

import datetime
import hashlib
from pathlib import Path

import httpx
from app_helper import make_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moarcoal.modules.provision import (
    BASIC_PENSION_CERTIFICATE,
    HEALTH_CONTRIBUTION_CERTIFICATE,
    AgreementMeaning,
    BasicPensionCertificate,
    HealthContributionCertificate,
    TaxMeaning,
)
from moarcoal.modules.provision.basic_pension.entries import PensionLine
from moarcoal.modules.provision.findings import (
    AGREEMENT_WITHOUT_CERTIFICATE,
    CERTIFICATE_WITHOUT_AGREEMENT,
)
from moarcoal.modules.provision.health_certificate.entries import (
    Characteristic,
    ContributionKind,
    ContributionLine,
)
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Document,
    Issuer,
    Put,
    Store,
)
from moarcoal.values.engine import Values
from moarcoal.values.findings import Finding, FindingList, Severity

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
USER = "anna"
NUMBER = "RR-4711-0815"
HEALTH = TaxMeaning.PRIVATE_HEALTH_CARE
PENSION = TaxMeaning.BASIC_PENSION


def make_client(root: Path) -> tuple[httpx.Client, Store, FastAPI]:
    app = make_app(PORT, root, user=USER)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    return client, app.state.store, app


def add_issuer(store: Store, name: str = "Beispiel Kranken AG") -> Issuer:
    issuer = Issuer(owner=COMMON_OWNER, name=name)
    assert isinstance(store.apply([Put(issuer)]), Applied)
    return issuer


def add_health_certificate(
    store: Store,
    issuer: Issuer | None,
    year: int = 2025,
    characteristics: tuple[Characteristic, ...] = (Characteristic.PRIVATE,),
) -> HealthContributionCertificate:
    document = Document(
        owner=USER,
        site="Belege",
        path=f"krv-{year}.html",
        sha256=hashlib.sha256(f"krv{year}".encode()).hexdigest(),
        document_kind=HEALTH_CONTRIBUTION_CERTIFICATE.key,
        issuer=None if issuer is None else issuer.address,
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
    )
    lines = tuple(
        ContributionLine(
            art="Beiträge zur Krankenversicherung (Basisleistungen)",
            kind=ContributionKind.HEALTH_BASIC,
            merkmal=c.value,
            characteristic=c,
            cents=120_000,
            place=f"id-VaSt_KRV-Betrag-{n}",
        )
        for n, c in enumerate(characteristics)
    )
    certificate = HealthContributionCertificate(
        owner=USER, document=document.address, reader_version=1000, year=year, lines=lines
    )
    assert isinstance(store.apply([Put(document), Put(certificate)]), Applied)
    return certificate


def add_pension_certificate(
    store: Store, issuer: Issuer | None, number: str = NUMBER, year: int = 2025
) -> BasicPensionCertificate:
    document = Document(
        owner=USER,
        site="Belege",
        path=f"rue-{year}.html",
        sha256=hashlib.sha256(f"{number}{year}".encode()).hexdigest(),
        document_kind=BASIC_PENSION_CERTIFICATE.key,
        issuer=None if issuer is None else issuer.address,
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
    )
    line = PensionLine(paid_year=year, cents=120_000, place="id-VaSt_RUE-Betrag")
    certificate = BasicPensionCertificate(
        owner=USER,
        document=document.address,
        reader_version=1000,
        year=year,
        contract_number=number,
        lines=(line,),
    )
    assert isinstance(store.apply([Put(document), Put(certificate)]), Applied)
    return certificate


def add_agreement(
    store: Store,
    issuer: Issuer,
    meaning: TaxMeaning | None,
    name: str = "Vertrag",
    **fields: object,
) -> Agreement:
    agreement = Agreement(owner=USER, issuer=issuer.address, name=name, **fields)  # pyright: ignore[reportArgumentType]
    changes: list[Put] = [Put(agreement)]
    if meaning is not None:
        changes.append(
            Put(AgreementMeaning(owner=USER, agreement=agreement.address, meaning=meaning))
        )
    assert isinstance(store.apply(changes), Applied)
    return agreement


def findings(app: FastAPI, year: int = 2025) -> FindingList:
    store: Store = app.state.store
    values = Values(
        app.state.modules, store.state(), sites=store.sites, entry_kinds=store.entry_kinds
    )
    return values.finding_list(USER, year)


def mine(app: FastAPI, year: int = 2025) -> list[Finding]:
    """Die sichtbaren Befunde des Moduls Vorsorge (andere Module haben eigene)."""
    return [f for f in findings(app, year).visible if f.kind.startswith("provision.")]


def of_kind(app: FastAPI, kind: str, year: int = 2025) -> list[Finding]:
    return [f for f in findings(app, year).visible if f.kind == kind]


# --- Bescheinigung ohne Vertrag --------------------------------------------------------------


def test_a_health_certificate_without_a_contract_is_a_note_until_one_with_the_meaning_exists(
    tmp_path: Path,
) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store)
    certificate = add_health_certificate(store, issuer)

    (found,) = of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)
    assert found.severity is Severity.NOTE and found.target == certificate.address
    assert found.href == "/vorsorge?jahr=2025#vorsorge-bescheinigungen"

    # ein Vertrag des Ausstellers, aber ohne passende Bedeutung: der Befund bleibt
    add_agreement(store, issuer, TaxMeaning.DISABILITY)
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1


def test_the_health_finding_goes_when_a_matching_contract_exists(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store)
    add_health_certificate(store, issuer)
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1
    add_agreement(store, issuer, HEALTH)
    assert of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT) == []
    assert of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE) == []


def test_a_contract_of_another_issuer_does_not_match_a_health_certificate(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    add_health_certificate(store, add_issuer(store))
    add_agreement(store, add_issuer(store, "Andere Versicherung"), HEALTH)
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1


def test_a_pension_certificate_matches_by_number_and_meaning_only(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    add_pension_certificate(store, issuer)
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1
    add_agreement(store, issuer, PENSION, number="XX-1")  # andere Nummer
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1
    add_agreement(store, issuer, TaxMeaning.DISABILITY, name="Zweiter", number=f" {NUMBER.lower()}")
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1  # Nummer passt, Bedeutung nicht
    other = add_issuer(store, "Andere Rente AG")
    add_agreement(store, other, PENSION, name="Dritter", number=f"{NUMBER.lower()} ")
    assert of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT) == []  # Nummer und Bedeutung passen


def test_a_pension_certificate_with_the_right_contract_has_no_finding(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    add_pension_certificate(store, issuer)
    add_agreement(store, issuer, PENSION, number=NUMBER)
    assert mine(app) == []


def test_certificates_of_other_years_make_no_finding(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    add_health_certificate(store, add_issuer(store), year=2024)
    assert of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT) == []
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT, 2024)) == 1


# --- Vertrag ohne Bescheinigung --------------------------------------------------------------


def test_a_running_contract_without_a_certificate_is_a_note_until_one_is_there(
    tmp_path: Path,
) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store)
    contract = add_agreement(store, issuer, HEALTH, name="Basisschutz")

    (found,) = of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE)
    assert found.severity is Severity.NOTE and "„Basisschutz“" in found.message
    assert found.target == f"{contract.address}@2025"

    add_health_certificate(store, issuer)
    assert of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE) == []


def test_a_pension_contract_without_a_certificate_of_its_number(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    add_agreement(store, issuer, PENSION, name="Rürup", number=NUMBER)
    assert len(of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE)) == 1
    add_pension_certificate(store, issuer, number="XX-1")  # andere Nummer
    assert len(of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE)) == 1
    add_pension_certificate(store, issuer, number=NUMBER.lower(), year=2024)  # anderes Jahr
    assert len(of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE)) == 1
    add_pension_certificate(store, issuer)
    assert of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE) == []


def test_only_contracts_running_in_the_year_with_the_two_meanings_count(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store)
    add_agreement(store, issuer, HEALTH, name="Beendet", end=datetime.date(2024, 5, 1))
    add_agreement(store, issuer, HEALTH, name="Später", start=datetime.date(2026, 1, 2))
    add_agreement(store, issuer, TaxMeaning.DISABILITY, name="Andere Bedeutung")
    add_agreement(store, issuer, None, name="Ohne Bedeutung")
    assert mine(app) == []


def test_the_findings_never_name_the_contract_number(tmp_path: Path) -> None:
    _, store, app = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    add_pension_certificate(store, issuer)
    add_agreement(store, issuer, PENSION, name="Rürup", number="ZZ-9999-1234")
    found = mine(app)
    assert len(found) == 2
    for finding in found:
        assert NUMBER not in finding.message and "ZZ-9999-1234" not in finding.message


def test_the_findings_can_be_hidden_like_any_finding(tmp_path: Path) -> None:
    client, store, app = make_client(tmp_path)
    add_agreement(store, add_issuer(store), HEALTH)
    (found,) = of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE)
    data = {
        "year": "2025",
        "kind": found.kind,
        "target": found.identity[1],
        "fingerprint": found.fingerprint,
        "note": "Kommt später.",
    }
    assert client.post("/befunde/ausblenden", data=data, headers=ORIGIN).status_code == 303
    assert of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE) == []
    assert len(findings(app).hidden) == 1
    # für ein anderes Jahr ist es ein anderer Befund
    assert len(of_kind(app, AGREEMENT_WITHOUT_CERTIFICATE, 2026)) == 1


def test_the_findings_show_on_the_findings_page(tmp_path: Path) -> None:
    client, store, _ = make_client(tmp_path)
    add_health_certificate(store, add_issuer(store))
    page = client.get("/befunde?year=2025").text
    assert "Beitragsbescheinigung Kranken-/Pflegeversicherung 2025" in page


# --- Vertrag aus der Bescheinigung anlegen ---------------------------------------------------


def post_create(client: httpx.Client, certificate_id: str, year: int = 2025) -> httpx.Response:
    return client.post(
        f"/vorsorge/vertrag-aus-bescheinigung/{certificate_id}",
        data={"year": str(year)},
        headers=ORIGIN,
    )


def only[T](items: list[T]) -> T:
    assert len(items) == 1
    return items[0]


def test_creating_the_contract_from_a_pension_certificate_sets_everything_in_one_go(
    tmp_path: Path,
) -> None:
    client, store, app = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    certificate = add_pension_certificate(store, issuer)
    assert NUMBER in client.get("/vorsorge?jahr=2025").text  # Nummer nur auf der Seite

    response = post_create(client, certificate.id)

    assert response.status_code == 303 and response.headers["location"] == "/vorsorge?jahr=2025"
    contract = only(store.state().of_kind(Agreement))
    assert contract.issuer == issuer.address and contract.number == NUMBER
    assert contract.owner == USER and contract.category == "Versicherung"
    meaning = only(store.state().of_kind(AgreementMeaning))
    assert meaning.agreement == contract.address and meaning.meaning is PENSION
    assert mine(app) == []


def test_creating_the_contract_from_a_health_certificate_has_no_number(tmp_path: Path) -> None:
    client, store, app = make_client(tmp_path)
    issuer = add_issuer(store)
    certificate = add_health_certificate(store, issuer)

    assert post_create(client, certificate.id).status_code == 303

    contract = only(store.state().of_kind(Agreement))
    assert contract.issuer == issuer.address and contract.number == ""
    assert only(store.state().of_kind(AgreementMeaning)).meaning is HEALTH
    assert mine(app) == []


def test_the_page_offers_the_contract_only_where_it_can_be_created(tmp_path: Path) -> None:
    client, store, _ = make_client(tmp_path)
    with_issuer = add_health_certificate(store, add_issuer(store))
    page = client.get("/vorsorge?jahr=2025").text
    assert f"/vorsorge/vertrag-aus-bescheinigung/{with_issuer.id}" in page
    assert "Vertrag anlegen" in page

    other, store2, _ = make_client(tmp_path / "other")
    no_issuer = add_health_certificate(store2, None)
    page = other.get("/vorsorge?jahr=2025").text
    assert f"/vorsorge/vertrag-aus-bescheinigung/{no_issuer.id}" not in page
    assert "keinen Aussteller" in page


def test_without_an_issuer_nothing_is_created(tmp_path: Path) -> None:
    client, store, _ = make_client(tmp_path)
    certificate = add_health_certificate(store, None)
    response = post_create(client, certificate.id)
    assert response.status_code == 422
    assert store.state().of_kind(Agreement) == []
    assert store.state().of_kind(AgreementMeaning) == []


def test_a_clash_rejects_the_whole_operation_and_names_no_number(tmp_path: Path) -> None:
    client, store, _ = make_client(tmp_path)
    issuer = add_issuer(store, "Beispiel Rente AG")
    certificate = add_pension_certificate(store, issuer)
    add_agreement(store, issuer, TaxMeaning.DISABILITY, name="Anderer", number=NUMBER)

    response = post_create(client, certificate.id)

    assert response.status_code == 409 and "Vertragsnummer" in response.text
    assert len(store.state().of_kind(Agreement)) == 1
    assert len(store.state().of_kind(AgreementMeaning)) == 1
    errors = response.text.split('class="fehler"')[1].split("</ul>")[0]
    assert NUMBER not in errors


def test_an_unknown_certificate_is_not_found(tmp_path: Path) -> None:
    client, store, _ = make_client(tmp_path)
    assert post_create(client, "gibtsnicht").status_code == 404
    assert client.get("/vorsorge/vertrag-aus-bescheinigung/x").status_code == 405
    assert store.state().of_kind(Agreement) == []


def test_a_statutory_only_certificate_gives_no_finding_and_no_offer(tmp_path: Path) -> None:
    client, store, app = make_client(tmp_path)
    certificate = add_health_certificate(
        store, add_issuer(store), characteristics=(Characteristic.STATUTORY,)
    )
    assert of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT) == []
    assert f"/vorsorge/vertrag-aus-bescheinigung/{certificate.id}" not in (
        client.get("/vorsorge?jahr=2025").text
    )


def test_a_mixed_certificate_gives_the_finding_and_the_offer(tmp_path: Path) -> None:
    client, store, app = make_client(tmp_path)
    certificate = add_health_certificate(
        store,
        add_issuer(store),
        characteristics=(Characteristic.STATUTORY, Characteristic.PRIVATE),
    )
    assert len(of_kind(app, CERTIFICATE_WITHOUT_AGREEMENT)) == 1
    assert f"/vorsorge/vertrag-aus-bescheinigung/{certificate.id}" in (
        client.get("/vorsorge?jahr=2025").text
    )
