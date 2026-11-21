"""Tests: Felder der Anlage N verlinken die Erfassung im Modul Arbeit (#180)."""

from pathlib import Path

import httpx
from test_anlage_n import PLACE, YEAR, equipment, place, tax_year
from test_tax_year import make_client

from moarcoal.modules import MODULES
from moarcoal.modules.tax_year.anlage_n import (
    N_ABSENCE_DAYS,
    N_EQUIPMENT,
    N_WORKPLACE_DAYS,
    WORK_ABSENCE_DAYS,
    WORK_EQUIPMENT,
    WORK_HOMEOFFICE_DAYS,
    WORK_TRIP_DAYS,
    WORK_WORKDAYS,
)
from moarcoal.modules.tax_year.capture import foreign_refs
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.modules.work.wage_tax.values import GROSS_WAGES
from moarcoal.values.model import Amount, NotYetComputable, Period, Unit, ValueRef
from moarcoal.values.testing import fixed
from moarcoal.web.helpers import capture_links


def keys(refs: list[ValueRef]) -> list[str]:
    return [r.key for r in refs]


# --- Fremde Schlüssel aus dem Ergebnis ------------------------------------------------------


def test_amount_names_the_used_foreign_key() -> None:
    value = tax_year(equipment())
    assert keys(foreign_refs(value(N_EQUIPMENT, YEAR))) == [WORK_EQUIPMENT]


def test_not_yet_computable_names_the_first_foreign_key_of_the_chain() -> None:
    foreign = {**place(), (WORK_WORKDAYS, PLACE, YEAR): lambda ref: _not_yet(ref)}
    value = tax_year(foreign)
    assert keys(foreign_refs(value(N_WORKPLACE_DAYS, YEAR))) == [WORK_WORKDAYS]


def _not_yet(ref: ValueRef) -> NotYetComputable:
    return NotYetComputable(ref.key, ref.user, ref.time, ref.subject, "keine Eingabe")


def test_own_keys_are_followed_to_the_first_foreign_one() -> None:
    days = fixed(Amount.of(3, Unit.DAYS))
    foreign = {
        **place(),
        (WORK_ABSENCE_DAYS, PLACE, YEAR): days,
        (WORK_HOMEOFFICE_DAYS, PLACE, YEAR): days,
        (WORK_TRIP_DAYS, None, YEAR): days,
    }
    value = tax_year(foreign)
    assert sorted(keys(foreign_refs(value(N_ABSENCE_DAYS, YEAR)))) == sorted(
        [WORK_ABSENCE_DAYS, WORK_TRIP_DAYS, WORK_HOMEOFFICE_DAYS]
    )


# --- Erfassungsstelle des Moduls Arbeit -----------------------------------------------------


def test_work_names_where_to_capture() -> None:
    year = Period.year(2025)
    assert WORK.capture_url(WORK_EQUIPMENT, year, None) == (
        "Arbeitsmittel erfassen (Arbeit)",
        "/arbeit?jahr=2025",
    )
    label, url = WORK.capture_url(WORK_WORKDAYS, year, PLACE) or ("", "")
    assert label == "Erste Tätigkeitsstätte erfassen (Arbeit)"
    assert url == f"/arbeit/erste-taetigkeitsstaette/{PLACE.address.id}"
    assert WORK.capture_url(WORK_TRIP_DAYS, year, None) == (
        "Dienstreisen erfassen (Arbeit)",
        "/arbeit?jahr=2025",
    )
    assert WORK.capture_url(GROSS_WAGES, year, None) is None  # folgt mit dem Beleg (#181)


def test_capture_links_name_each_place_once() -> None:
    year = Period.year(2025)
    refs = [
        ValueRef(WORK_ABSENCE_DAYS, "anna", year, PLACE),
        ValueRef(WORK_HOMEOFFICE_DAYS, "anna", year, PLACE),
        ValueRef(WORK_TRIP_DAYS, "anna", year, None),
        ValueRef(GROSS_WAGES, "anna", year, None),
    ]
    links = capture_links(MODULES, refs)
    assert [label for label, _ in links] == [
        "Erste Tätigkeitsstätte erfassen (Arbeit)",
        "Dienstreisen erfassen (Arbeit)",
    ]


# --- Seite ----------------------------------------------------------------------------------


def test_page_links_the_capture_next_to_the_amount(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    client: httpx.Client = make_client(tmp_path / "daten", site)
    page = client.get("/steuerjahr/anlage-n/2025/10").text
    assert '<a href="/arbeit?jahr=2025">Arbeitsmittel erfassen (Arbeit)</a>' in page
