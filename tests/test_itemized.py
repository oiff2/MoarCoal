"""Tests: Felder mit Einzelangaben (Art `Itemized`), erfundene Gruppe der KAP 2025.

Die Gruppe E0900011 (Bezeichnung), E0900012 (Betrag), E0900013 (Summe) steht in
`fixtures/strukturen_einzel`; welche Werte die Gruppen der VOR füllen, gehört nicht hierher.
"""

import datetime
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from moarcoal.modules.tax_year import ProtocolLine, ProtocolReading, registration
from moarcoal.modules.tax_year.anlage_view import AnlageView, ValueContent, anlage_view
from moarcoal.modules.tax_year.anlagen import Anlage, year_anlagen
from moarcoal.modules.tax_year.field_catalog import CollectItems, SumOfRounded
from moarcoal.modules.tax_year.fields import (
    Computed,
    Direction,
    FieldMeaning,
    FormField,
    Itemized,
    ItemizedAmount,
    NotComputed,
    Rounding,
)
from moarcoal.modules.tax_year.protocol_check import latest_reading, protocol_findings
from moarcoal.modules.tax_year.special_parts import PageParams
from moarcoal.registration import ModuleState
from moarcoal.storage import Document, Entry, EntryAddress, State
from moarcoal.values.calculation import Calculation
from moarcoal.values.findings import Finding
from moarcoal.values.model import (
    Amount,
    ExposedValue,
    NotYetComputable,
    Period,
    Unit,
    UserInputLocator,
    ValueKey,
    ValueResult,
)
from moarcoal.values.testing import evaluate

USER = "anna"
YEAR = 2025
STRUCTURES = Path(__file__).parent / "fixtures" / "strukturen_einzel"
KEY = ValueKey("tax_year.kap_insurances")
ADDRESS = EntryAddress(kind="Insurance", id="A" * 10)
FIRST_INDEX, SECOND_INDEX = "1_1-1-1", "2_1-1-1"


def collect_of(*items: tuple[str, int]) -> CollectItems:
    """Einzelposten mit Bezeichnung und Cent; ungerundet wie jeder Einzelposten."""

    def collect(calculation: Calculation, field: FormField) -> None:
        for label, cents in items:
            calculation.item(label, Amount.eur_cents(cents), UserInputLocator(ADDRESS))

    return collect


# Einzelposten 10,20 und 5,01 € als Ausgabe: je Einzelangabe aufgerundet 11 und 6, Summe 17
# (die Summe der Ungerundeten, 15,21 €, würde zu 16 aufgerundet).
TWO = collect_of(("Haftpflicht Muster", 1020), ("Unfall Beispiel", 501))


def kap(
    collect: CollectItems = TWO,
    direction: Direction = Direction.EXPENSE,
    *,
    all_structure_fields: bool = False,
) -> Anlage:
    total = Computed(Unit.EUR, Rounding.WHOLE_EUROS, SumOfRounded(collect), direction)
    meaning = FieldMeaning("E0900013", Itemized("E0900011", "E0900012", total), KEY)
    return Anlage(
        "KAP",
        {YEAR: (meaning,)},
        all_structure_fields=all_structure_fields,
        structure_directory=STRUCTURES,
    )


def line(elster_id: str, content: str, index: str = "") -> ProtocolLine:
    return ProtocolLine(
        elster_id=elster_id,
        form="KAP",
        form_line="",
        label="Beispiel",
        content=content,
        index=index,
        data_name=f"id-KAP-Beispiel-{elster_id}" + (f"_usb{index}" if index else ""),
    )


def item_lines(label: str, amount: str, index: str) -> list[ProtocolLine]:
    return [line("E0900011", label, index), line("E0900012", amount, index)]


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


def state_of(entries: Sequence[Entry], anlage: Anlage) -> ModuleState:
    return ModuleState(State({e.address: e for e in entries}), registration((anlage,)), USER)


def findings_of(entries: Sequence[Entry]) -> list[Finding]:
    anlage = kap()
    values = evaluate([registration((anlage,))], entries)
    return protocol_findings(state_of(entries, anlage), values, YEAR, (anlage,))


def value_of(anlage: Anlage) -> ValueResult:
    return evaluate([registration((anlage,))]).get(KEY, USER, Period.year(YEAR))


def view_of(anlage: Anlage) -> AnlageView:
    values = evaluate([registration((anlage,))])
    (found,) = year_anlagen((anlage,), YEAR, None)
    shown = anlage_view(
        state_of([], anlage), values, (), lambda refs: [], found, None, PageParams()
    )
    assert shown is not None
    return shown


# --- Rechnung ---------------------------------------------------------------------------------


def test_every_einzelangabe_is_rounded_by_the_rule_of_the_field_and_the_sum_adds_them() -> None:
    result = value_of(kap())

    assert isinstance(result, ExposedValue)
    assert result.amount == Amount(Decimal(17), Unit.EUR)
    assert [(i.label, i.amount.value) for i in result.items] == [
        ("Haftpflicht Muster", Decimal("10.20")),  # die Einzelposten bleiben ungerundet
        ("Unfall Beispiel", Decimal("5.01")),
    ]
    steps = [s.text for s in result.workings.steps if s.kind == "step"]
    assert any("aufgerundet" in text for text in steps)  # der Rechenweg nennt die Rundung


def test_the_rounding_direction_of_the_field_decides_for_each_einzelangabe() -> None:
    result = value_of(kap(direction=Direction.INCOME))

    assert isinstance(result, ExposedValue) and result.amount.value == 15  # 10 + 5, abgerundet


def test_without_einzelposten_the_group_is_not_yet_computable_never_empty() -> None:
    result = value_of(kap(collect_of()))

    assert isinstance(result, NotYetComputable)
    assert "Einzelposten" in result.reason


def test_einzelangaben_hand_out_the_rounded_amounts_with_the_label() -> None:
    result = value_of(kap())
    assert isinstance(result, ExposedValue)
    (field,) = kap().fields[YEAR]
    assert field.itemized is not None

    assert field.itemized.amounts(result.items) == (
        ItemizedAmount("Haftpflicht Muster", Decimal(11)),
        ItemizedAmount("Unfall Beispiel", Decimal(6)),
    )
    assert ItemizedAmount("  Unfall  BEISPIEL ", Decimal(1)).key == "unfallbeispiel"


def test_label_and_amount_are_part_of_the_field_not_rows_of_their_own() -> None:
    fields = kap(all_structure_fields=True).fields[YEAR]

    assert [f.elster_id for f in fields] == ["E0900010", "E0900013"]
    assert isinstance(fields[0].kind, NotComputed)
    assert fields[1].computed and fields[1].key == KEY


# --- Zeile des Felds --------------------------------------------------------------------------


def test_the_row_shows_each_einzelangabe_and_the_sum() -> None:
    (row,) = view_of(kap()).rows

    assert isinstance(row.content, ValueContent)
    assert row.content.itemized == (
        ItemizedAmount("Haftpflicht Muster", Decimal(11)),
        ItemizedAmount("Unfall Beispiel", Decimal(6)),
    )
    assert isinstance(row.content.result, ExposedValue) and row.content.result.amount.value == 17


def test_a_group_without_einzelposten_shows_no_einzelangaben() -> None:
    (row,) = view_of(kap(collect_of())).rows

    assert isinstance(row.content, ValueContent)
    assert row.content.itemized == () and isinstance(row.content.result, NotYetComputable)


# --- Abgleich mit dem Protokoll ---------------------------------------------------------------


def matching(*extra: ProtocolLine) -> list[Entry]:
    return protocol(
        *item_lines("Haftpflicht Muster", "11", FIRST_INDEX),
        *item_lines("Unfall Beispiel", "6", SECOND_INDEX),
        line("E0900013", "17"),
        *extra,
    )


def test_the_same_einzelangaben_match_without_a_finding() -> None:
    assert findings_of(matching()) == []


def test_the_same_labels_in_another_order_and_spelling_match_without_a_finding() -> None:
    entries = protocol(
        *item_lines("unfall  beispiel", "6", FIRST_INDEX),
        *item_lines(" HAFTPFLICHT MUSTER", "11", SECOND_INDEX),
        line("E0900013", "17"),
    )

    assert findings_of(entries) == []


def test_a_missing_einzelangabe_is_a_finding() -> None:
    entries = protocol(*item_lines("Haftpflicht Muster", "11", FIRST_INDEX), line("E0900013", "17"))

    (finding,) = findings_of(entries)

    assert finding.kind == "tax_year.protocol_missing"
    assert "Unfall Beispiel" in finding.message and "fehlt" in finding.message


def test_a_surplus_einzelangabe_is_a_finding() -> None:
    entries = matching(*item_lines("Rechtsschutz Probe", "40", "3_1-1-1"))

    (finding,) = findings_of(entries)

    assert finding.kind == "tax_year.protocol_extra_item"
    assert "Rechtsschutz Probe" in finding.message


def test_a_deviating_amount_is_a_finding_for_that_einzelangabe() -> None:
    entries = protocol(
        *item_lines("Haftpflicht Muster", "11", FIRST_INDEX),
        *item_lines("Unfall Beispiel", "7", SECOND_INDEX),
        line("E0900013", "17"),
    )

    (finding,) = findings_of(entries)

    assert finding.kind == "tax_year.protocol_deviation"
    assert "Unfall Beispiel" in finding.message


def test_an_einzelangabe_that_is_not_rounded_in_the_protocol_names_the_rounding() -> None:
    entries = protocol(
        *item_lines("Haftpflicht Muster", "10,20", FIRST_INDEX),
        *item_lines("Unfall Beispiel", "6", SECOND_INDEX),
        line("E0900013", "17"),
    )

    (finding,) = findings_of(entries)

    assert "nicht gerundet" in finding.message


def test_the_sum_is_compared_like_an_ordinary_field() -> None:
    entries = protocol(
        *item_lines("Haftpflicht Muster", "11", FIRST_INDEX),
        *item_lines("Unfall Beispiel", "6", SECOND_INDEX),
        line("E0900013", "16"),  # die Summe der ungerundeten Beträge, gerundet
    )

    (finding,) = findings_of(entries)

    assert finding.kind == "tax_year.protocol_deviation"
    assert "Einzelangabe" not in finding.message


def test_the_reading_keeps_the_index_of_each_line() -> None:
    reading = latest_reading(state_of(matching(), kap()), YEAR)

    assert reading is not None
    assert {(r.elster_id, r.index) for r in reading.lines if r.elster_id != "E0900013"} == {
        ("E0900011", FIRST_INDEX),
        ("E0900012", FIRST_INDEX),
        ("E0900011", SECOND_INDEX),
        ("E0900012", SECOND_INDEX),
    }
