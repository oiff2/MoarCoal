"""Tests: Regeln eines Felds, direkt am Feld (runden, anzeigen, Protokoll lesen, Abweichung)."""

from decimal import Decimal

import pytest

from moarcoal.modules.tax_year.fields import (
    AmbiguousLines,
    Direction,
    FormField,
    NotANumber,
    Rounding,
)
from moarcoal.values.model import Unit, ValueKey

KEY = ValueKey("demo.x")
EXPENSE = FormField(
    KEY, None, "56", "Arbeitsmittel", Unit.EUR, Rounding.WHOLE_EUROS, Direction.EXPENSE
)
INCOME = FormField(KEY, None, "1", "Erstattung", Unit.EUR, Rounding.WHOLE_EUROS, Direction.INCOME)
CENTS = FormField(KEY, None, "2", "Lohnsteuer", Unit.EUR, Rounding.EURO_CENTS)
KM = FormField(KEY, None, "30", "Entfernung", Unit.KM, Rounding.WHOLE_KM)
DAYS = FormField(KEY, None, "29", "Tage", Unit.DAYS, Rounding.NONE)


# --- runden -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "rounded", "reason"),
    [
        (EXPENSE, "86.40", "87", "aufgerundet, Ausgabe"),
        (INCOME, "86.60", "86", "abgerundet, Einnahme"),
        (KM, "12.4", "12", "auf volle km abgerundet"),
        (KM, "12.9", "12", "auf volle km abgerundet"),
        (CENTS, "86.60", "86.60", None),
        (EXPENSE, "87", "87", None),  # passt schon: kein Grund, kein Schritt
        (DAYS, "220", "220", None),
    ],
)
def test_round(field: FormField, value: str, rounded: str, reason: str | None) -> None:
    assert field.round(Decimal(value)) == (Decimal(rounded), reason)


def test_euro_field_needs_a_direction_exactly_when_it_takes_whole_euros() -> None:
    with pytest.raises(ValueError, match="Richtung"):
        FormField(KEY, None, "1", "x", Unit.EUR, Rounding.WHOLE_EUROS)
    with pytest.raises(ValueError, match="Richtung"):
        FormField(KEY, None, "1", "x", Unit.EUR, Rounding.EURO_CENTS, Direction.EXPENSE)


# --- anzeigen -----------------------------------------------------------------------------------


def test_show_whole_euros_without_cents_but_never_cuts_cents_off() -> None:
    assert EXPENSE.show(Decimal(1234)) == "1.234 €"
    assert EXPENSE.show(Decimal("86.40")) == "86,40 €"
    assert CENTS.show(Decimal(87)) == "87,00 €"
    assert KM.show(Decimal("12.4")) == "12,4 km"


# --- Protokollfelder lesen ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "number"),
    [("1.234,56", "1234.56"), ("220", "220"), ("49,90 €", "49.90"), ("49,90 EUR", "49.90")],
)
def test_reads_german_numbers(content: str, number: str) -> None:
    assert CENTS.read_protocol([content]) == Decimal(number)


@pytest.mark.parametrize("content", ["abc", "1,2,3", ""])
def test_content_that_is_no_number(content: str) -> None:
    assert EXPENSE.read_protocol([content]) == NotANumber(content)


def test_euro_lines_are_summed_days_and_km_twice_are_ambiguous() -> None:
    assert EXPENSE.read_protocol(["49,90", "36,50"]) == Decimal("86.40")
    assert DAYS.read_protocol(["100", "120"]) == AmbiguousLines(2)
    assert KM.read_protocol(["12", "12"]) == AmbiguousLines(2)


# --- Abweichung nennen --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected", "transferred", "text"),
    [
        (EXPENSE, "87", "86.40", "nicht gerundet: 86,40 € statt 87 €."),
        (EXPENSE, "87", "86", "um 1 € abgerundet, zu deinen Ungunsten (Wert 87 €)."),
        (EXPENSE, "87", "88", "um 1 € aufgerundet, zu deinen Gunsten (Wert 87 €)."),
        (INCOME, "86", "87", "um 1 € aufgerundet, zu deinen Ungunsten (Wert 86 €)."),
        (INCOME, "86", "85", "um 1 € abgerundet, zu deinen Gunsten (Wert 86 €)."),
        (KM, "12", "13", "um 1 km aufgerundet, zu deinen Gunsten (Wert 12 km)."),
        (KM, "12", "12.4", "nicht gerundet: 12,4 km statt 12 km."),
        (EXPENSE, "87", "90", "Wert 87 €, Protokoll 90 €."),  # mehr als Rundung
        (DAYS, "220", "219", "Wert 220 Tage, Protokoll 219 Tage."),  # Tage: keine Seite
        (CENTS, "86.60", "86.61", "Wert 86,60 €, Protokoll 86,61 €."),
    ],
)
def test_explain_deviation(field: FormField, expected: str, transferred: str, text: str) -> None:
    assert field.explain_deviation(Decimal(expected), Decimal(transferred)) == text
