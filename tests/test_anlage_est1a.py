"""Tests: Katalog der ESt 1 A 2025; Inhalt der Felder aus den Angaben zur Person und den
Eingaben zur Person im Steuerjahr (#167; nur erfundene Werte)."""

import datetime
from pathlib import Path

from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading, registration
from moarcoal.modules.tax_year.anlage_est1a import ANLAGE_EST1A, IN_THIS_RETURN
from moarcoal.modules.tax_year.entries import YearPersonInput
from moarcoal.modules.tax_year.field_checks import field_checks
from moarcoal.modules.tax_year.fields import NotComputed, TextSource
from moarcoal.modules.tax_year.person_input import field_reasons, field_texts
from moarcoal.modules.tax_year.protocol_check import AMBIGUOUS, DEVIATION, MISSING
from moarcoal.modules.tax_year.registered import ANLAGEN
from moarcoal.registration import ModuleState
from moarcoal.storage import (
    Applied,
    Document,
    Entry,
    PersonalDetails,
    Put,
    Rejected,
    Religion,
    ReligionMembership,
    State,
    open_store,
)
from moarcoal.values.findings import Finding
from moarcoal.values.testing import evaluate

PORT = 4711
USER = "anna"
IBAN = "DE89370400440532013000"  # Beispiel-IBAN aus Dokumentationen
ID_NUMBER = "86095742719"  # Beispiel-Steuer-ID aus Dokumentationen
FIELDS = ANLAGE_EST1A.fields[2025]
STRUCTURE = ANLAGE_EST1A.structures[2025]
BY_ID = {f.elster_id: f for f in FIELDS}
_SELECTION = BY_ID[IN_THIS_RETURN].kind
assert isinstance(_SELECTION, TextSource)
CHOICES: tuple[str, ...] = _SELECTION.choices


def details(**more: object) -> PersonalDetails:
    base: dict[str, object] = {
        "owner": USER,
        "first_name": "Erika",
        "last_name": "Mustermann",
        "birth_date": datetime.date(1980, 2, 3),
        "id_number": ID_NUMBER,
        "title": "Dr.",
        "street": "Beispielweg",
        "house_number": "12a",
        "postal_code": "12345",
        "city": "Beispielstadt",
        "iban": IBAN,
    }
    return PersonalDetails.model_validate({**base, **more})


def module_state(*entries: Entry | None) -> ModuleState:
    found = [e for e in entries if e is not None]
    return ModuleState(State({e.address: e for e in found}), registration(), USER)


def texts(
    person: PersonalDetails | None, year_input: YearPersonInput | None = None, year: int = 2025
) -> dict[str, str]:
    return field_texts(module_state(person, year_input), FIELDS, year)


def since(year: int, month: int, day: int, religion: Religion) -> ReligionMembership:
    return ReligionMembership(from_date=datetime.date(year, month, day), religion=religion)


# --- Katalog ----------------------------------------------------------------------------------


def test_est1a_is_registered_with_its_stored_structure_and_lists_every_field() -> None:
    assert ANLAGE_EST1A in ANLAGEN
    structure = STRUCTURE
    assert structure.form == "ESt1A" and not structure.provisional
    assert [f.elster_id for f in FIELDS] == [f.e_kennung for f in structure.fields]
    # keine Beträge, keine Eintippfelder
    assert all(isinstance(f.kind, NotComputed | TextSource) for f in FIELDS)


def test_text_fields_are_the_ones_with_a_source_in_the_person() -> None:
    with_source = {f.elster_id for f in FIELDS if isinstance(f.kind, TextSource)}
    assert with_source == {
        "E0100008", "E0100081", "E0100401", "E0100201", "E0100301", "E0101004", "E0101104",
        "E0101206", "E0100601", "E0100602", "E0100403", "E0100402", "E0102102", "E0102603",
        IN_THIS_RETURN,
    }  # fmt: skip


# --- Inhalt ----------------------------------------------------------------------------------


def test_contents_come_from_the_details_as_text_as_entered_in_elster() -> None:
    found = texts(details(), YearPersonInput(owner=USER, year=2025, occupation="Beispielberuf"))

    assert found["E0100301"] == "Erika" and found["E0100201"] == "Mustermann"
    assert found["E0100401"] == "03.02.1980"
    assert found["E0100081"] == ID_NUMBER and found["E0101004"] == "Dr."
    assert (found["E0101104"], found["E0101206"]) == ("Beispielweg", "12a")
    assert (found["E0100601"], found["E0100602"]) == ("12345", "Beispielstadt")
    assert found["E0102102"] == IBAN and "E0102603" not in found
    assert found["E0100403"] == "Beispielberuf"


def test_year_inputs_fill_phone_and_selection() -> None:
    entry = YearPersonInput(owner=USER, year=2025, phone="0123 456", in_this_return=CHOICES[0])
    found = texts(details(), entry)
    assert found["E0100008"] == "0123 456" and found[IN_THIS_RETURN] == CHOICES[0]
    assert "E0100403" not in found  # Beruf nicht angegeben: noch nicht berechenbar


def test_what_is_missing_is_not_there_never_empty() -> None:
    bare = PersonalDetails(owner=USER, first_name="Erika", last_name="Mustermann")

    assert texts(bare) == {"E0100301": "Erika", "E0100201": "Mustermann"}
    assert texts(None) == {}


def test_a_foreign_iban_goes_to_the_foreign_field() -> None:
    found = texts(details(iban="GB82WEST12345698765432"))
    assert found["E0102603"] == "GB82WEST12345698765432" and "E0102102" not in found


def test_year_inputs_of_another_year_do_not_count() -> None:
    other = YearPersonInput(owner=USER, year=2024, occupation="Beispielberuf")
    assert "E0100403" not in texts(details(), other)


# --- Religion am 31.12. ----------------------------------------------------------------------


def test_religion_on_31_12_follows_the_history_of_the_year() -> None:
    person = details(
        religions=(
            since(2000, 1, 1, Religion.EVANGELICAL),
            since(2025, 6, 1, Religion.NONE),  # Austritt im Jahr: am 31.12. keine
        )
    )

    assert "E0100402" not in texts(person)  # Änderung im Jahr: nicht „ganzjährig gleichbleibend“
    assert texts(person, year=2024)["E0100402"] == "Evangelisch"  # früheres Jahr bleibt
    assert texts(person, year=2026)["E0100402"] == "nicht kirchensteuerpflichtig"


def test_a_change_in_the_year_names_the_reason() -> None:
    person = details(
        religions=(since(2000, 1, 1, Religion.EVANGELICAL), since(2025, 6, 1, Religion.NONE))
    )
    state = module_state(person)
    assert "2025" in field_reasons(state, FIELDS, 2025)["E0100402"]
    assert field_reasons(state, FIELDS, 2024) == {}


def test_an_exit_in_the_following_year_leaves_the_year_unchanged() -> None:
    person = details(
        religions=(since(2000, 1, 1, Religion.ROMAN_CATHOLIC), since(2026, 3, 1, Religion.NONE))
    )
    assert texts(person)["E0100402"] == "Römisch-katholisch"


def test_without_a_history_for_the_year_the_religion_is_not_known() -> None:
    person = details(religions=(since(2026, 1, 1, Religion.EVANGELICAL),))
    assert "E0100402" not in texts(person)
    assert "E0100402" not in texts(details())


def test_every_religion_has_an_option_of_mein_elster() -> None:
    options = STRUCTURE.get("E0100402").options
    for religion in Religion:
        found = texts(details(religions=(since(2000, 1, 1, religion),)))["E0100402"]
        assert found in options


# --- Auswahl „In dieser Steuererklärung“ mit festen Optionen ------------------------------------


def test_the_selection_offers_the_options_of_the_structure_without_no_answer() -> None:
    options = STRUCTURE.get(IN_THIS_RETURN).options
    assert tuple(o for o in options if o != "Keine Angabe") == CHOICES
    assert len(CHOICES) == 4


def test_the_write_path_rejects_a_text_that_is_not_an_option(tmp_path: Path) -> None:
    store = open_store(tmp_path, registration().kinds)
    bad = store.apply([Put(YearPersonInput(owner=USER, year=2025, in_this_return="Ich"))])
    assert isinstance(bad, Rejected)
    assert "In dieser Steuererklärung" in " ".join(bad.reasons.values())
    good = store.apply([Put(YearPersonInput(owner=USER, year=2025, in_this_return=CHOICES[1]))])
    assert isinstance(good, Applied)


def test_a_year_without_a_catalog_takes_any_text(tmp_path: Path) -> None:
    store = open_store(tmp_path, registration().kinds)
    result = store.apply([Put(YearPersonInput(owner=USER, year=2024, in_this_return="Ich"))])
    assert isinstance(result, Applied)


# --- Abgleich mit dem Protokoll ----------------------------------------------------------------


def est1a_line(elster_id: str, content: str, index: str = "1_1-1-1") -> ProtocolLine:
    return ProtocolLine(
        elster_id=elster_id,
        form="ESt1A",
        form_line="9",
        label="Beispiel",
        content=content,
        index=index,
        data_name=f"id-ESt1A-Allg-{elster_id}_usb{index}",
    )


def findings_for(lines: list[ProtocolLine]) -> list[Finding]:
    person = PersonalDetails(owner=USER, first_name="Erika", last_name="Mustermann")
    document = Document(
        owner=USER,
        site="Belege",
        path="p.html",
        sha256=f"{1:064x}",
        document_kind="transfer_protocol",
        period_start=datetime.date(2025, 1, 1),
        period_end=datetime.date(2025, 12, 31),
        taken_in_at=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
    )
    reading = ProtocolReading(
        owner=USER, document=document.address, year=2025, reader_version=2, lines=tuple(lines)
    )
    registered = registration((ANLAGE_EST1A,))
    assert registered.findings is not None
    state = module_state(person, document, reading)
    return list(registered.findings(state, evaluate([registered]), 2025))


def protocol_findings(found: list[Finding]) -> list[Finding]:
    return [f for f in found if f.kind in {DEVIATION, MISSING, AMBIGUOUS}]


def test_a_text_that_matches_the_protocol_gives_no_finding() -> None:
    found = findings_for([est1a_line("E0100301", "Erika"), est1a_line("E0100201", "Mustermann")])
    assert protocol_findings(found) == []


def test_a_different_text_deviates_and_the_message_does_not_name_the_values() -> None:
    found = findings_for([est1a_line("E0100301", "Berta"), est1a_line("E0100201", "Mustermann")])
    (finding,) = [f for f in protocol_findings(found) if f.kind == DEVIATION]
    assert "E0100301" in finding.message
    assert "Erika" not in finding.message and "Berta" not in finding.message


def test_a_known_text_missing_in_the_protocol_is_reported() -> None:
    found = findings_for([est1a_line("E0100201", "Mustermann")])
    (finding,) = protocol_findings(found)
    assert finding.kind == MISSING and "E0100301" in finding.message


def test_a_text_twice_in_the_protocol_is_ambiguous() -> None:
    found = findings_for(
        [
            est1a_line("E0100301", "Erika", "1_1-1-1"),
            est1a_line("E0100301", "Erika", "2_1-1-1"),
            est1a_line("E0100201", "Mustermann"),
        ]
    )
    assert [f.kind for f in protocol_findings(found)] == [AMBIGUOUS]


def test_a_text_that_is_not_known_is_not_compared() -> None:
    found = findings_for(
        [
            est1a_line("E0100301", "Erika"),
            est1a_line("E0100201", "Mustermann"),
            est1a_line("E0100403", "Beispielberuf"),
        ]
    )
    assert protocol_findings(found) == []


# --- Zeile des Felds ----------------------------------------------------------------------------


def test_a_text_field_with_content_fits_when_the_protocol_shows_something() -> None:
    field = BY_ID["E0100301"]
    shown = {"E0100301": "Erika"}
    (check,) = field_checks(
        field, transferred=shown, frozen=None, printed={}, findings=[], content="Erika"
    )
    assert check.fits
    (unknown,) = field_checks(
        field, transferred=shown, frozen=None, printed={}, findings=[], content=None
    )
    assert not unknown.fits and unknown.shown == "Erika"
