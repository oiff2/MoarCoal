"""Tests: Kirchensteuerzahlung (Eintragsart des Steuerjahrs) und die Felder der Anlage SA."""

import datetime
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi.testclient import TestClient

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.tax_year.anlage_sa import ANLAGE_SA, SA_PAID, SA_REFUNDED
from moarcoal.modules.tax_year.church_tax import ChurchTaxPayment
from moarcoal.modules.tax_year.fields import Computed, Direction, Rounding
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.storage import (
    Applied,
    Delete,
    Document,
    Entry,
    EntryAddress,
    PersonalDetails,
    Put,
    Rejected,
    Religion,
    ReligionMembership,
    entry_checksum,
    open_store,
)
from moarcoal.values.model import (
    Backing,
    ExposedValue,
    NotApplicable,
    NotYetComputable,
    Period,
    Unit,
    UserInputLocator,
)
from moarcoal.values.testing import evaluate

PORT = 4711
USER = "anna"
SHA = "a" * 64


def payment(
    when: str = "2025-03-10",
    cents: int = 100050,
    *,
    refunded: bool = False,
    kind: str = "Nachzahlung 2023",
    document: EntryAddress | None = None,
    entry_id: str | None = None,
) -> ChurchTaxPayment:
    data: dict[str, object] = {
        "owner": USER,
        "date": when,
        "amount_cents": cents,
        "refunded": refunded,
        "benefit_type": kind,
        "document": document,
    }
    if entry_id:
        data["id"] = entry_id
    return ChurchTaxPayment.model_validate(data)


def member(*memberships: tuple[str, Religion]) -> PersonalDetails:
    return PersonalDetails(
        owner=USER,
        first_name="Erika",
        last_name="Mustermann",
        religions=tuple(
            ReligionMembership(from_date=datetime.date.fromisoformat(day), religion=religion)
            for day, religion in memberships
        ),
    )


CHURCH_MEMBER = member(("2000-01-01", Religion.EVANGELICAL))
NO_CHURCH = member(("2000-01-01", Religion.NONE))
NOT_STATED = member()


def result(*entries: Entry, key: str = SA_PAID, year: int = 2025):
    return evaluate([TAX_YEAR], entries).get(key, USER, Period.year(year))


def amount_of(*entries: Entry, key: str = SA_PAID) -> Decimal:
    found = result(*entries, key=key)
    assert isinstance(found, ExposedValue)
    return found.amount.value


# --- Katalog -------------------------------------------------------------------------------------


def test_sa_is_registered_with_its_stored_structure() -> None:
    (sa,) = [a for a in ANLAGEN if a.form == "SA"]
    assert sa.structures[2025].form == "SA" and not sa.structures[2025].provisional
    fields = ANLAGE_SA.fields[2025]
    assert [f.elster_id for f in fields] == [f.e_kennung for f in sa.structures[2025].fields]


def test_paid_expense_rounds_up_and_refunded_income_rounds_down() -> None:
    paid, refunded = [f for f in ANLAGE_SA.fields[2025] if f.computed]
    assert isinstance(paid.kind, Computed) and isinstance(refunded.kind, Computed)
    assert (paid.elster_id, paid.key, paid.kind.direction) == (
        "E0107601",
        SA_PAID,
        Direction.EXPENSE,
    )
    assert (refunded.elster_id, refunded.key, refunded.kind.direction) == (
        "E0107602",
        SA_REFUNDED,
        Direction.INCOME,
    )
    for kind in (paid.kind, refunded.kind):
        assert (kind.unit, kind.rounding) == (Unit.EUR, Rounding.WHOLE_EUROS)


# --- Zählen im Jahr der Zahlung ------------------------------------------------------------------


def test_a_payment_counts_in_the_year_of_its_date_and_is_rounded_up() -> None:
    entries = (
        CHURCH_MEMBER,
        payment("2025-12-31", 100050),
        payment("2026-01-01", 5000),
        payment("2024-12-31", 7000),
    )

    assert amount_of(*entries) == Decimal(
        1001
    )  # 1.000,50 € aufgerundet; 2024 und 2026 zählen nicht


def test_paid_and_refunded_are_separate_and_refunds_round_down() -> None:
    entries = (
        CHURCH_MEMBER,
        payment(cents=20000),
        payment(cents=30050, refunded=True),
        payment("2025-06-01", 10000, refunded=True),
    )

    assert amount_of(*entries, key=SA_PAID) == Decimal(200)
    assert amount_of(*entries, key=SA_REFUNDED) == Decimal(400)  # 400,50 abgerundet


def test_each_payment_is_a_line_item_with_assumed_backing_and_its_kind() -> None:
    first, second = payment(cents=100, kind="Vorauszahlung"), payment("2025-06-01", 200)
    found = result(CHURCH_MEMBER, first, second)

    assert isinstance(found, ExposedValue)
    items = {str(i.locator.entry_address): i for i in found.items}
    assert set(items) == {str(first.address), str(second.address)}
    assert all(isinstance(i.locator, UserInputLocator) for i in items.values())
    assert all(i.backing is Backing.ASSUMED for i in items.values())
    assert "Vorauszahlung" in items[str(first.address)].label


# --- Nie eine stille Null ------------------------------------------------------------------------


def test_church_tax_applies_but_no_payment_is_not_yet_computable_never_zero() -> None:
    for key in (SA_PAID, SA_REFUNDED):
        found = result(CHURCH_MEMBER, key=key)
        assert isinstance(found, NotYetComputable)
        assert "Kirchensteuerzahlung" in found.reason


def test_payments_of_another_year_do_not_make_the_year_computable() -> None:
    assert isinstance(result(CHURCH_MEMBER, payment("2024-05-05")), NotYetComputable)


def test_no_church_all_year_means_the_fields_fall_away() -> None:
    for key in (SA_PAID, SA_REFUNDED):
        found = result(NO_CHURCH, key=key)
        assert isinstance(found, NotApplicable)
        assert "Angaben zur Person" in found.reason


def test_missing_religion_is_not_yet_computable_with_a_hint_to_the_person() -> None:
    for details in (NOT_STATED, None):
        found = result(*([] if details is None else [details]))
        assert isinstance(found, NotYetComputable)
        assert "Angaben zur Person" in found.reason


def test_entries_decide_when_the_religion_is_open() -> None:
    assert amount_of(NOT_STATED, payment(cents=5000)) == Decimal(50)


def test_a_payment_counts_even_after_leaving_the_church() -> None:
    """Nachzahlung oder Erstattung nach dem Austritt: Zahlung zählt im Jahr der Zahlung."""
    assert amount_of(NO_CHURCH, payment(cents=5000)) == Decimal(50)


def test_with_payments_in_the_year_a_direction_without_entries_falls_away_not_zero() -> None:
    found = result(CHURCH_MEMBER, payment(), key=SA_REFUNDED)

    assert isinstance(found, NotApplicable)
    assert "erstattet" in found.reason


# --- Schreibweg ----------------------------------------------------------------------------------


def apply_put(tmp_path: Path, *entries: Entry):
    store = open_store(tmp_path, TAX_YEAR.kinds)
    return store, store.apply([Put(e) for e in entries])


def test_the_write_path_accepts_a_payment_and_files_it_by_its_date_year(tmp_path: Path) -> None:
    _, result_ = apply_put(tmp_path, payment("2024-12-30"))

    assert isinstance(result_, Applied)
    assert (tmp_path / "users" / USER / "tax_year" / "2024.json").exists()


@pytest.mark.parametrize("cents", [0, -5])
def test_an_amount_must_be_positive(cents: int) -> None:
    with pytest.raises(ValueError, match="amount_cents"):
        payment(cents=cents)


def test_the_kind_of_benefit_is_required() -> None:
    with pytest.raises(ValueError, match="benefit_type"):
        payment(kind="")


def test_the_date_must_lie_in_a_supported_year() -> None:
    with pytest.raises(ValueError, match="Jahr"):
        payment("1800-01-01")


def test_the_write_path_rejects_a_document_that_does_not_exist(tmp_path: Path) -> None:
    ghost = EntryAddress(kind="Document", id="AAAAAAAAAA")

    _, rejected = apply_put(tmp_path, payment(document=ghost))

    assert isinstance(rejected, Rejected)
    assert "Dokument" in " ".join(rejected.reasons.values())


def test_the_write_path_rejects_a_document_of_another_user(tmp_path: Path) -> None:
    other = Document(owner="bert", site="s", path="a.pdf", sha256=SHA)

    _, rejected = apply_put(tmp_path, other, payment(document=other.address))

    assert isinstance(rejected, Rejected)


def test_a_payment_with_its_document_is_accepted_and_blocks_deleting_the_document(
    tmp_path: Path,
) -> None:
    mine = Document(owner=USER, site="s", path="a.pdf", sha256=SHA)
    store, applied = apply_put(tmp_path, mine, payment(document=mine.address))
    assert isinstance(applied, Applied)

    blocked = store.apply([Delete(mine.address, entry_checksum(mine))])

    assert isinstance(blocked, Rejected)


# --- Seite ---------------------------------------------------------------------------------------


def make_client(root: Path) -> httpx.Client:
    app = make_app(PORT, root, user=USER)
    return TestClient(
        app,
        base_url=f"http://127.0.0.1:{PORT}",
        follow_redirects=False,
        headers={"Origin": f"http://127.0.0.1:{PORT}"},
    )


FORM = {"date": "2025-04-02", "amount": "1.234,50", "kind": "Nachzahlung 2023", "direction": "paid"}


def stored(root: Path, year: int = 2025) -> dict[str, dict[str, object]]:
    path = root / "users" / USER / "tax_year" / f"{year}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_the_sa_page_shows_the_fields_and_the_capture_form(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    page = client.get("/steuerjahr/anlage-sa/2025")

    assert page.status_code == 200
    assert "E0107601" in page.text and "Neue Kirchensteuerzahlung" in page.text
    assert "noch nicht berechenbar" in page.text.lower()


def test_creating_a_payment_through_the_page_writes_it_and_the_field_shows_the_sum(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post("/steuerjahr/kirchensteuer", data=FORM)

    assert response.status_code == 303
    (saved,) = stored(tmp_path).values()
    assert saved["amount_cents"] == 123450 and saved["refunded"] is False
    assert saved["benefit_type"] == "Nachzahlung 2023"
    page = client.get("/steuerjahr/anlage-sa/2025")
    assert "Nachzahlung 2023" in page.text  # Einzelposten nennt die Art


def test_an_invalid_form_is_shown_again_with_reasons_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post("/steuerjahr/kirchensteuer", data=FORM | {"amount": "abc"})

    assert response.status_code == 422
    assert "Betrag" in response.text and not stored(tmp_path)


def test_a_payment_can_be_changed_and_deleted(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/steuerjahr/kirchensteuer", data=FORM)
    (address,) = stored(tmp_path)
    entry_id = address.rpartition(":")[2]
    page = client.get("/steuerjahr/anlage-sa/2025")
    checksum = page.text.split('name="checksum" value="')[1].split('"')[0]

    changed = client.post(
        f"/steuerjahr/kirchensteuer/{entry_id}",
        data=FORM | {"direction": "refunded", "checksum": checksum},
    )
    assert changed.status_code == 303
    assert stored(tmp_path)[address]["refunded"] is True

    page = client.get("/steuerjahr/anlage-sa/2025")
    checksum = page.text.split('name="checksum" value="')[1].split('"')[0]
    gone = client.post(
        f"/steuerjahr/kirchensteuer/{entry_id}/loeschen", data={"checksum": checksum}
    )
    assert gone.status_code == 303 and not stored(tmp_path)
