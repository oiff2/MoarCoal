"""Baustein AfA der Datenebene (`values.depreciation`): linear, monatsgenau, auf Cent genau.

Unabhängig davon, was abgeschrieben wird; die Regeln der Arbeitsmittel prüft
`test_equipment_depreciation.py`. Alle Beträge sind erfunden.
"""

import datetime

import pytest

from moarcoal.values.depreciation import Depreciation, linear


def schedule(cents: int, start: datetime.date, total_months: int) -> dict[int, Depreciation]:
    years = range(start.year - 1, start.year + total_months // 12 + 3)
    found = {year: linear(cents, start, total_months, year) for year in years}
    return {year: share for year, share in found.items() if share is not None}


def test_three_years_from_march() -> None:
    shares = schedule(120_000, datetime.date(2025, 3, 14), 36)

    assert shares == {
        2025: Depreciation(33_333, 10, 36),
        2026: Depreciation(40_000, 12, 36),
        2027: Depreciation(40_000, 12, 36),
        2028: Depreciation(6_667, 2, 36),
    }


def test_building_at_two_percent_from_july() -> None:
    """Gebäude mit 2 % im Jahr: 600 Monate, im ersten Jahr 6 Monate, dann 2 % je Jahr."""
    shares = schedule(30_000_000, datetime.date(2024, 7, 1), 600)

    assert shares[2024] == Depreciation(300_000, 6, 600)
    assert shares[2025] == Depreciation(600_000, 12, 600)
    assert shares[2074] == Depreciation(300_000, 6, 600)  # die restlichen 6 Monate
    assert max(shares) == 2074
    assert sum(s.cents for s in shares.values()) == 30_000_000


def test_three_percent_takes_the_rest_in_the_last_year() -> None:
    """3 % im Jahr sind 400 Monate (33 Jahre und 4 Monate); Beginn im Januar."""
    shares = schedule(1_000_000, datetime.date(2025, 1, 1), 400)

    assert shares[2025] == Depreciation(30_000, 12, 400)
    assert shares[2058] == Depreciation(10_000, 4, 400)
    assert sum(s.cents for s in shares.values()) == 1_000_000


@pytest.mark.parametrize(
    ("cents", "month", "months"),
    [(100_001, 1, 36), (99_999, 7, 84), (123_457, 12, 60), (95_201, 2, 24), (1, 6, 480)],
)
def test_cent_rounding_never_loses_or_gains_a_cent(cents: int, month: int, months: int) -> None:
    shares = schedule(cents, datetime.date(2025, month, 1), months)

    assert sum(s.cents for s in shares.values()) == cents


def test_nothing_before_the_start_and_after_the_end() -> None:
    start = datetime.date(2025, 12, 31)

    assert linear(12_000, start, 12, 2024) is None
    assert linear(12_000, start, 12, 2025) == Depreciation(1_000, 1, 12)
    assert linear(12_000, start, 12, 2026) == Depreciation(11_000, 11, 12)
    assert linear(12_000, start, 12, 2027) is None


def test_a_duration_below_one_month_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="mindestens ein Monat"):
        linear(100, datetime.date(2025, 1, 1), 0, 2025)
