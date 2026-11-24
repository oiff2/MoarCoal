"""Tests: Jahresbeitrag im Modul Vorsorge (Eintragsart, Schreibweg, Seite, Wert, VOR Z. 27);
nur tmp_path, erfundene Daten."""

import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules import MODULES
from moarcoal.modules.provision import (
    REGISTRATION,
    AgreementMeaning,
    AnnualContribution,
    TaxMeaning,
)
from moarcoal.modules.provision.annual_contribution.changes import (
    build_contribution,
    contribution_changes,
    contribution_of,
    delete_changes,
    net_cents,
)
from moarcoal.modules.provision.annual_contribution.values import PRIVATE_HEALTH_EXTRA
from moarcoal.modules.tax_year.anlage_vor import VOR_PRIVATE_EXTRA
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    COMMON_OWNER,
    Agreement,
    Applied,
    Delete,
    Document,
    EntryAddress,
    Issuer,
    Put,
    Rejected,
    Store,
    entry_checksum,
)
from moarcoal.values.model import (
    Amount,
    Backing,
    DocumentLocator,
    ExposedValue,
    NotYetComputable,
    Period,
    Source,
    UserInputLocator,
)
from moarcoal.values.testing import evaluate

PORT = 4711
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
USER = "anna"
YEAR = 2025
PRIVATE = TaxMeaning.PRIVATE_HEALTH_CARE


def make_client(root: Path) -> tuple[httpx.Client, Store]:
    app = make_app(PORT, root, user=USER)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    return client, app.state.store


def add_agreement(
    store: Store,
    name: str = "Zusatzversicherung",
    meaning: TaxMeaning | None = PRIVATE,
    owner: str = USER,
    **fields: object,
) -> Agreement:
    partner = Issuer(owner=COMMON_OWNER, name=f"Beispielversicherung {name}")
    agreement = Agreement(owner=owner, issuer=partner.address, name=name, **fields)  # pyright: ignore[reportArgumentType]
    changes = [Put(partner), Put(agreement)]
    if meaning is not None:
        changes.append(
            Put(AgreementMeaning(owner=owner, agreement=agreement.address, meaning=meaning))
        )
    assert isinstance(store.apply(changes), Applied)
    return agreement


def add_document(store: Store, owner: str = USER) -> Document:
    document = Document(
        owner=owner,
        site="Belege",
        path="rechnung.pdf",
        sha256="1" * 64,
        document_kind="invoice",
    )
    assert isinstance(store.apply([Put(document)]), Applied)
    return document


def contribution(
    agreement: Agreement,
    amount: int,
    refund: int | None = None,
    year: int = YEAR,
    document: EntryAddress | None = None,
    owner: str = USER,
) -> AnnualContribution:
    return AnnualContribution(
        owner=owner,
        agreement=agreement.address,
        year=year,
        amount_cents=amount,
        refund_cents=refund,
        document=document,
    )


def own_state(store: Store) -> ModuleState:
    return ModuleState(store.state(), REGISTRATION, USER)


def contributions(store: Store) -> list[AnnualContribution]:
    return own_state(store).all(AnnualContribution)


def value(store: Store, key: str = PRIVATE_HEALTH_EXTRA) -> ExposedValue | NotYetComputable:
    entries = list(store.state().entries.values())
    result = evaluate(MODULES, entries).get(key, USER, Period.year(YEAR))
    assert isinstance(result, ExposedValue | NotYetComputable), result
    return result


# --- Eintragsart und Schreibweg ---------------------------------------------------------------


def test_create_change_and_delete_a_contribution(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    entry = contribution(agreement, 123_456)
    assert isinstance(store.apply(contribution_changes(None, entry, "")), Applied)
    found = contribution_of(own_state(store), agreement, YEAR)
    assert found is not None and found == entry
    changed = found.model_copy(update={"amount_cents": 100_000, "refund_cents": 5_000})
    assert isinstance(
        store.apply(contribution_changes(found, changed, entry_checksum(found))), Applied
    )
    assert [(c.amount_cents, c.refund_cents) for c in contributions(store)] == [(100_000, 5_000)]
    current = contributions(store)[0]
    assert isinstance(store.apply(delete_changes(current, entry_checksum(current))), Applied)
    assert contributions(store) == []


def test_a_second_contribution_for_agreement_and_year_is_rejected(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(store.apply([Put(contribution(agreement, 100))]), Applied)
    result = store.apply([Put(contribution(agreement, 200))])
    assert isinstance(result, Rejected)
    assert "schon einen Jahresbeitrag" in " ".join(result.reasons.values())
    assert isinstance(
        store.apply([Put(contribution(agreement, 100)), Put(contribution(agreement, 1))]), Rejected
    )
    assert isinstance(store.apply([Put(contribution(agreement, 200, year=2024))]), Applied)
    other = add_agreement(store, "Weitere")
    assert isinstance(store.apply([Put(contribution(other, 300))]), Applied)


def test_only_an_agreement_of_the_user_can_have_a_contribution(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    foreign = add_agreement(store, "Fremd", owner="berta")
    assert isinstance(store.apply([Put(contribution(foreign, 100))]), Rejected)
    assert isinstance(store.apply([Put(contribution(foreign, 100, owner="berta"))]), Applied)
    missing = contribution(foreign, 100).model_copy(
        update={"agreement": foreign.address.model_copy(update={"id": "A" * 10})}
    )
    assert isinstance(store.apply([Put(missing)]), Rejected)


def test_the_agreement_needs_a_meaning_checked_by_the_write_path(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    plain = add_agreement(store, "Ohne", meaning=None)
    result = store.apply([Put(contribution(plain, 100))])
    assert isinstance(result, Rejected)
    assert "keine Steuerliche Bedeutung" in " ".join(result.reasons.values())
    # Vertrag und Bedeutung im selben Vorgang gehen
    meaning = AgreementMeaning(owner=USER, agreement=plain.address, meaning=TaxMeaning.DISABILITY)
    assert isinstance(store.apply([Put(meaning), Put(contribution(plain, 100))]), Applied)


def test_the_proof_has_to_be_a_document_of_the_user(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    foreign = add_document(store, owner="berta")
    result = store.apply([Put(contribution(agreement, 100, document=foreign.address))])
    assert isinstance(result, Rejected)
    with pytest.raises(ValueError):
        contribution(agreement, 100, document=agreement.address)
    mine = add_document(store)
    assert isinstance(
        store.apply([Put(contribution(agreement, 100, document=mine.address))]), Applied
    )
    # ein verwendeter Beleg lässt sich nicht löschen
    assert isinstance(store.apply([Delete(mine.address, expected=entry_checksum(mine))]), Rejected)


def test_deleting_the_agreement_takes_the_contribution_along(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(store.apply([Put(contribution(agreement, 100))]), Applied)
    result = store.apply([Delete(agreement.address, expected=entry_checksum(agreement))])
    assert isinstance(result, Applied)
    assert contributions(store) == []


def test_negative_amounts_are_not_a_contribution() -> None:
    partner = Issuer(owner=COMMON_OWNER, name="Beispiel AG")
    agreement = Agreement(owner=USER, issuer=partner.address, name="Vertrag")
    with pytest.raises(ValueError):
        contribution(agreement, -1)
    with pytest.raises(ValueError):
        contribution(agreement, 1, refund=-1)


def test_net_is_the_amount_minus_the_refund_and_a_missing_refund_is_no_refund() -> None:
    partner = Issuer(owner=COMMON_OWNER, name="Beispiel AG")
    agreement = Agreement(owner=USER, issuer=partner.address, name="Vertrag")
    assert net_cents(contribution(agreement, 10_000, 2_500)) == 7_500
    assert net_cents(contribution(agreement, 10_000, 0)) == 10_000
    assert net_cents(contribution(agreement, 10_000)) == 10_000


def test_build_contribution_from_the_form() -> None:
    partner = Issuer(owner=COMMON_OWNER, name="Beispiel AG")
    agreement = Agreement(owner=USER, issuer=partner.address, name="Vertrag")

    def build(**fields: str):
        return build_contribution(fields, USER, agreement, YEAR)

    entry, errors = build(amount="1.234,50", refund="", document="")
    assert errors == [] and entry is not None
    assert (entry.amount_cents, entry.refund_cents, entry.document) == (123_450, None, None)
    entry, _ = build(amount="0", refund="0,00")
    assert entry is not None and (entry.amount_cents, entry.refund_cents) == (0, 0)
    for bad in ({"amount": ""}, {"amount": "abc"}, {"amount": "-5"}, {"amount": "1,234"}):
        entry, errors = build(**bad)
        assert entry is None and errors
    entry, errors = build(amount="10", refund="abc")  # nicht lesbar ist keine fehlende Erstattung
    assert entry is None and any("Erstattung" in e for e in errors)
    entry, errors = build(amount="10", document="nope!")
    assert entry is None and errors


# --- Ausgewiesener Wert -----------------------------------------------------------------------


def test_the_value_sums_two_agreements_net_of_refunds_as_items_with_the_agreement_name(
    tmp_path: Path,
) -> None:
    _, store = make_client(tmp_path)
    first = add_agreement(store, "Wahlleistungen A")
    second = add_agreement(store, "Wahlleistungen B")
    changes = [
        Put(contribution(first, 120_040, 20_000)),
        Put(contribution(second, 30_005)),
    ]
    assert isinstance(store.apply(changes), Applied)

    result = value(store)

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.eur_cents(130_045)  # ungerundet
    assert [(i.label, i.amount.value) for i in result.items] == [
        ("Wahlleistungen A", Decimal("1000.40")),
        ("Wahlleistungen B", Decimal("300.05")),
    ]
    assert all(isinstance(i.locator, UserInputLocator) for i in result.items)
    assert result.backing is Backing.ASSUMED


def test_a_proof_makes_the_item_proven(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    document = add_document(store)
    entry = contribution(agreement, 50_000, document=document.address)
    assert isinstance(store.apply([Put(entry)]), Applied)

    result = value(store)

    assert isinstance(result, ExposedValue)
    (item,) = result.items
    assert isinstance(item.locator, DocumentLocator)
    assert item.locator.document == document.address and item.locator.source is Source.PROOF
    assert result.backing is Backing.PROVEN


def test_without_a_contribution_the_value_is_not_yet_computable_never_zero(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    assert isinstance(value(store), NotYetComputable)  # kein solcher Vertrag
    add_agreement(store, "Zusatz")
    result = value(store)
    assert isinstance(result, NotYetComputable) and "Zusatz" in result.reason


def test_an_explicit_zero_is_a_value(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(store.apply([Put(contribution(agreement, 0))]), Applied)
    result = value(store)
    assert isinstance(result, ExposedValue) and result.amount == Amount.eur_cents(0)


def test_one_running_agreement_without_contribution_blocks_the_sum(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    first = add_agreement(store, "Mit")
    add_agreement(store, "Ohne")
    assert isinstance(store.apply([Put(contribution(first, 100))]), Applied)
    result = value(store)
    assert isinstance(result, NotYetComputable) and "Ohne" in result.reason


def test_an_agreement_that_does_not_run_in_the_year_needs_no_contribution(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    first = add_agreement(store, "Läuft")
    add_agreement(store, "Beendet", end=datetime.date(2024, 5, 1))
    assert isinstance(store.apply([Put(contribution(first, 100))]), Applied)
    assert isinstance(value(store), ExposedValue)


def test_only_private_health_agreements_other_years_and_own_contributions_count(
    tmp_path: Path,
) -> None:
    _, store = make_client(tmp_path)
    private = add_agreement(store, "Privat")
    liability = add_agreement(store, "Haftpflicht", meaning=TaxMeaning.ACCIDENT_LIABILITY_RISK)
    foreign = add_agreement(store, "Fremd", owner="berta")
    changes = [
        Put(contribution(private, 10_000)),
        Put(contribution(private, 99_900, year=2024)),
        Put(contribution(liability, 5_000)),
        Put(contribution(foreign, 7_000, owner="berta")),
    ]
    assert isinstance(store.apply(changes), Applied)
    result = value(store)
    assert isinstance(result, ExposedValue)
    assert result.amount == Amount.eur_cents(10_000)
    assert [i.label for i in result.items] == ["Privat"]


def test_removing_the_meaning_takes_the_agreement_out_of_the_sum(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    agreement = add_agreement(store)
    assert isinstance(store.apply([Put(contribution(agreement, 100))]), Applied)
    (meaning,) = ModuleState(store.state(), REGISTRATION, USER).all(AgreementMeaning)
    assert isinstance(
        store.apply([Delete(meaning.address, expected=entry_checksum(meaning))]), Applied
    )
    assert isinstance(value(store), NotYetComputable)


def test_line_27_is_rounded_up_only_at_the_field(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    first = add_agreement(store, "A")
    second = add_agreement(store, "B")
    changes = [Put(contribution(first, 50_005)), Put(contribution(second, 50_005, 10_000))]
    assert isinstance(store.apply(changes), Applied)
    raw = value(store)
    assert isinstance(raw, ExposedValue) and raw.amount == Amount.eur_cents(90_010)  # 900,10
    field = value(store, VOR_PRIVATE_EXTRA)
    assert isinstance(field, ExposedValue)
    assert field.amount == Amount.eur_cents(90_100)  # Ausgabe: aufrunden auf 901
    assert isinstance(value(store, VOR_PRIVATE_EXTRA), ExposedValue)


def test_line_27_without_contribution_is_not_yet_computable(tmp_path: Path) -> None:
    _, store = make_client(tmp_path)
    add_agreement(store)
    assert isinstance(value(store, VOR_PRIVATE_EXTRA), NotYetComputable)


def test_the_registration_lists_the_kind_the_value_and_the_capture_page() -> None:
    assert AnnualContribution.__name__ in {k.model.__name__ for k in REGISTRATION.kinds}
    assert PRIVATE_HEALTH_EXTRA in {d.entry.key for d in REGISTRATION.values}


# --- Seite ------------------------------------------------------------------------------------


def post(client: httpx.Client, agreement: Agreement, path: str = "", **fields: str):
    data = {"year": str(YEAR)} | fields
    return client.post(f"/vorsorge/jahresbeitrag/{agreement.id}{path}", data=data, headers=ORIGIN)


def test_creating_changing_and_deleting_on_the_page(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    agreement = add_agreement(store)
    page = client.get(f"/vorsorge?jahr={YEAR}").text
    assert "noch nicht erfasst" in page

    response = post(client, agreement, amount="1.234,50", refund="34,50")
    assert response.status_code == 303 and response.headers["location"] == f"/vorsorge?jahr={YEAR}"
    (found,) = contributions(store)
    assert (found.amount_cents, found.refund_cents) == (123_450, 3_450)
    page = client.get(f"/vorsorge?jahr={YEAR}").text
    assert "1.234,50" in page and "34,50" in page

    response = post(client, agreement, amount="900", refund="", checksum=entry_checksum(found))
    assert response.status_code == 303
    (changed,) = contributions(store)
    assert (changed.id, changed.amount_cents, changed.refund_cents) == (found.id, 90_000, None)

    response = post(client, agreement, "/loeschen", checksum=entry_checksum(changed))
    assert response.status_code == 303 and contributions(store) == []


def test_a_rejected_input_shows_the_page_with_the_reason_and_the_input(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    agreement = add_agreement(store)
    response = post(client, agreement, amount="abc")
    assert response.status_code == 422 and "Betrag:" in response.text and "abc" in response.text
    assert contributions(store) == []
    assert post(client, agreement, amount="10").status_code == 303
    stale = post(client, agreement, amount="20", checksum="")
    assert stale.status_code == 409 and "Inzwischen geändert" in stale.text
    assert [c.amount_cents for c in contributions(store)] == [1_000]


def test_the_page_offers_only_agreements_with_a_meaning(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    add_agreement(store, "Mit Bedeutung")
    add_agreement(store, "Ohne Bedeutung", meaning=None)
    page = client.get(f"/vorsorge?jahr={YEAR}").text
    section = page.split('id="vorsorge-jahresbeitraege"')[1].split('id="vorsorge-bescheinigungen"')[
        0
    ]
    assert "Mit Bedeutung" in section and "Ohne Bedeutung" not in section


def test_a_foreign_agreement_or_missing_contribution_is_not_found(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)
    foreign = add_agreement(store, "Fremd", owner="berta")
    assert post(client, foreign, amount="1").status_code == 404
    mine = add_agreement(store)
    assert post(client, mine, "/loeschen").status_code == 404
    assert contributions(store) == []
