"""Angaben zur Person erweitert (#200): Prüfziffer, IBAN-Prüfsumme, Religion, Sperrliste, Seite.

Nur erfundene Beispielwerte (aus tools/erlaubte_beispielwerte.txt), nur tmp_path.
"""

import datetime
from pathlib import Path

import pytest
from test_personal_details import ORIGIN, PERSON, USER, checksum_of, created, make_client, state_of

from moarcoal.personal_details import (
    PersonalDetailsInvalid,
    PersonForm,
    church_tax_applies,
    details_of,
    parse_date,
    personal_details_changes,
    religion_on,
)
from moarcoal.storage import (
    Applied,
    Change,
    PersonalDetails,
    Put,
    Rejected,
    Religion,
    ReligionMembership,
    State,
    entry_checksum,
    open_store,
)
from moarcoal.storage.identifiers import iban_problem, id_number_problem, normalize_iban

ID_NUMBER = "86095742719"  # Beispiel aus der Dokumentation, Prüfziffer stimmt
IBAN = "DE89 3704 0044 0532 0130 00"  # Beispiel-IBAN, Prüfsumme stimmt
DENYLIST = "common/derived-denylist.txt"


def day(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def member(since: str, religion: Religion) -> ReligionMembership:
    return ReligionMembership(from_date=day(since), religion=religion)


def with_history(*history: ReligionMembership) -> PersonalDetails:
    return PersonalDetails(
        owner=USER, first_name="Erika", last_name="Musterfrau", religions=history
    )


# --- Prüfziffer und Prüfsumme ------------------------------------------------------------------


def test_id_number_accepts_the_example() -> None:
    assert id_number_problem(ID_NUMBER) is None


@pytest.mark.parametrize(
    "text",
    ["86095742710", "8609574271", "860957427190", "0609574271x", "06095742710", "abcdefghijk"],
)
def test_id_number_rejects_wrong_digits_length_and_leading_zero(text: str) -> None:
    assert id_number_problem(text) is not None


def test_iban_accepts_the_example_with_and_without_spaces() -> None:
    assert iban_problem(normalize_iban(IBAN)) is None
    assert iban_problem(normalize_iban(IBAN.lower())) is None
    assert normalize_iban(" de89 3704 0044 0532 0130 00 ") == "DE89370400440532013000"


@pytest.mark.parametrize("text", ["DE89370400440532013001", "DE8937040044053201300", "89DE", "DE"])
def test_iban_rejects_wrong_checksum_and_shape(text: str) -> None:
    assert iban_problem(text) is not None


# --- Religion am 31.12. und Kirchensteuer -----------------------------------------------------


def test_religion_on_a_day_is_the_latest_entry_up_to_then() -> None:
    details = with_history(
        member("2024-03-01", Religion.NONE), member("2000-01-01", Religion.EVANGELICAL)
    )
    assert religion_on(details, day("1999-12-31")) is None  # nicht bekannt, nicht „keine“
    assert religion_on(details, day("2000-01-01")) is Religion.EVANGELICAL
    assert religion_on(details, day("2023-12-31")) is Religion.EVANGELICAL
    assert religion_on(details, day("2024-12-31")) is Religion.NONE


def test_church_tax_for_a_year() -> None:
    member_all_year = with_history(member("2000-01-01", Religion.ROMAN_CATHOLIC))
    left_in_march = with_history(
        member("2000-01-01", Religion.EVANGELICAL), member("2025-03-01", Religion.NONE)
    )
    joined_in_march = with_history(
        member("2000-01-01", Religion.NONE), member("2025-03-01", Religion.EVANGELICAL)
    )
    never = with_history(member("2000-01-01", Religion.NONE))
    unknown = with_history()
    starts_in_june = with_history(member("2025-06-01", Religion.NONE))
    assert church_tax_applies(member_all_year, 2025) is True
    assert church_tax_applies(left_in_march, 2025) is True  # bis März Mitglied
    assert church_tax_applies(left_in_march, 2026) is False
    assert church_tax_applies(joined_in_march, 2025) is True
    assert church_tax_applies(never, 2025) is False
    assert church_tax_applies(unknown, 2025) is None  # nie eine stille Null
    assert church_tax_applies(starts_in_june, 2025) is None  # Jan.-Mai unbekannt
    assert church_tax_applies(starts_in_june, 2026) is False


# --- Kern: Formular -> Änderungen ----------------------------------------------------------------


def test_parse_date_takes_iso_and_german_dates() -> None:
    assert parse_date("1990-05-17") == day("1990-05-17")
    assert parse_date(" 17.05.1990 ") == day("1990-05-17")
    assert parse_date("31.02.1990") is None and parse_date("morgen") is None


def filled() -> PersonForm:
    return PersonForm(
        birth_date="17.05.1990",
        id_number="86 095 742 719",
        title="Dr.",
        street="Beispielweg",
        house_number="12a",
        postal_code="12345",
        city="Beispielstadt",
        iban=IBAN.lower(),
        account_holder="Erika Musterfrau",
        religions=(("2000-01-01", "evangelisch"), ("", ""), ("01.03.2025", "keine")),
    )


def put_details(changes: list[Change]) -> PersonalDetails:
    found = [
        c.entry for c in changes if isinstance(c, Put) and isinstance(c.entry, PersonalDetails)
    ]
    assert len(found) == 1
    return found[0]


def test_changes_normalise_and_store_all_fields() -> None:
    changes = personal_details_changes(State({}), USER, "Erika", "Musterfrau", more=filled())
    saved = put_details(changes)
    assert saved.birth_date == day("1990-05-17")
    assert (saved.id_number, saved.iban) == (ID_NUMBER, "DE89370400440532013000")
    assert (saved.title, saved.street, saved.house_number) == ("Dr.", "Beispielweg", "12a")
    assert (saved.postal_code, saved.city) == ("12345", "Beispielstadt")
    assert saved.account_holder == "Erika Musterfrau"
    assert saved.religions == (
        member("2000-01-01", Religion.EVANGELICAL),
        member("2025-03-01", Religion.NONE),
    )


def test_changes_without_more_keep_the_other_fields() -> None:
    first = put_details(
        personal_details_changes(State({}), USER, "Erika", "Musterfrau", more=filled())
    )
    state = State({e.address: e for e in [first]})
    again = put_details(
        personal_details_changes(state, USER, "Erika", "Neu", entry_checksum(first))
    )
    assert again.last_name == "Neu"
    assert (again.id_number, again.iban) == (first.id_number, first.iban)
    assert again.religions == first.religions


def test_empty_fields_are_not_given_not_empty_strings() -> None:
    changes = personal_details_changes(State({}), USER, "Erika", "Musterfrau", more=PersonForm())
    saved = put_details(changes)
    assert saved.id_number is None and saved.iban is None and saved.birth_date is None
    assert saved.religions == ()


def test_changes_collect_every_problem_in_german() -> None:
    bad = PersonForm(
        birth_date="gestern",
        id_number="86095742710",
        iban="DE89370400440532013001",
        religions=(("2000-01-01", "evangelisch"), ("2000-01-01", "keine"), ("", "rk"), ("x", "")),
    )
    with pytest.raises(PersonalDetailsInvalid) as error:
        personal_details_changes(State({}), USER, "", "Musterfrau", more=bad)
    text = " | ".join(error.value.problems)
    for part in ("Vorname", "Geburtsdatum", "Identifikationsnummer", "IBAN", "Religion"):
        assert part in text
    assert len(error.value.problems) >= 6


# --- Vorgang: Prüfungen gelten für jeden Schreibweg -----------------------------------------------


def stored(tmp_path: Path, **fields: object) -> Applied | Rejected:
    entry = PersonalDetails(owner=USER, first_name="Erika", last_name="Musterfrau", **fields)  # pyright: ignore[reportArgumentType]
    return open_store(tmp_path, []).apply([Put(entry)])


def test_the_operation_rejects_a_wrong_check_digit_and_checksum(tmp_path: Path) -> None:
    bad_id = stored(tmp_path, id_number="86095742710")
    assert isinstance(bad_id, Rejected)
    assert "Identifikationsnummer" in " ".join(bad_id.reasons.values())
    bad_iban = stored(tmp_path, iban="DE89370400440532013001")
    assert isinstance(bad_iban, Rejected)
    assert "IBAN" in " ".join(bad_iban.reasons.values())
    assert isinstance(stored(tmp_path, id_number=ID_NUMBER, iban="DE89370400440532013000"), Applied)


def test_the_operation_rejects_two_entries_on_one_date(tmp_path: Path) -> None:
    twice = stored(
        tmp_path,
        religions=(member("2000-01-01", Religion.NONE), member("2000-01-01", Religion.EVANGELICAL)),
    )
    assert isinstance(twice, Rejected)
    assert "Religion" in " ".join(twice.reasons.values())


def test_id_number_and_iban_are_in_the_derived_denylist(tmp_path: Path) -> None:
    result = stored(tmp_path, id_number=ID_NUMBER, iban="DE89370400440532013000", title="Dr.")
    assert isinstance(result, Applied)
    lines = (tmp_path / DENYLIST).read_text(encoding="utf-8").splitlines()
    assert lines == [ID_NUMBER, "DE89370400440532013000"]


def test_without_id_number_and_iban_nothing_is_listed(tmp_path: Path) -> None:
    assert isinstance(stored(tmp_path, street="Beispielweg"), Applied)
    listed = tmp_path / DENYLIST
    assert not listed.exists() or listed.read_text(encoding="utf-8") == ""


# --- Seite ---------------------------------------------------------------------------------------

FORM = {
    "extended": "1",
    "birth_date": "1990-05-17",
    "id_number": ID_NUMBER,
    "title": "Dr.",
    "street": "Beispielweg",
    "house_number": "12a",
    "postal_code": "12345",
    "city": "Beispielstadt",
    "iban": IBAN,
    "account_holder": "Erika Musterfrau",
    "religion_from_0": "2000-01-01",
    "religion_0": "evangelisch",
    "religion_from_1": "",
    "religion_1": "",
}


def test_the_page_saves_and_shows_the_details(tmp_path: Path) -> None:
    client = created(tmp_path)
    data = {**PERSON, **FORM, "checksum": checksum_of(client)}
    response = client.post("/person", data=data, headers=ORIGIN)
    assert (response.status_code, response.headers["location"]) == (303, "/person")
    saved = details_of(state_of(tmp_path), USER)
    assert saved is not None and saved.id_number == ID_NUMBER
    page = client.get("/person").text
    for shown in (ID_NUMBER, "DE89370400440532013000", "Beispielweg", "1990-05-17", "evangelisch"):
        assert shown in page


def test_the_page_names_a_wrong_check_digit_and_stores_nothing(tmp_path: Path) -> None:
    client = created(tmp_path)
    data = {**PERSON, **FORM, "id_number": "86095742710", "checksum": checksum_of(client)}
    response = client.post("/person", data=data, headers=ORIGIN)
    assert response.status_code == 422
    assert "Identifikationsnummer" in response.text and "86095742710" in response.text
    saved = details_of(state_of(tmp_path), USER)
    assert saved is not None and saved.id_number is None


def test_the_start_page_asks_for_the_name_only(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/").text
    assert 'name="id_number"' not in page and 'name="iban"' not in page
    assert 'name="id_number"' in created(tmp_path).get("/person").text
