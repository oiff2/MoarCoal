"""Tests: Felder der Anlage N verlinken die Erfassung im Modul Arbeit (#180)."""

import datetime
import hashlib
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
from moarcoal.modules.work.wage_tax.reading import WAGE_TAX_CERTIFICATE
from moarcoal.modules.work.wage_tax.values import (
    GROSS_WAGES,
    INCOME_TAX_WITHHELD,
    SOLI_WITHHELD,
    TAX_CLASS,
)
from moarcoal.registration import ModuleState
from moarcoal.storage import Document, State
from moarcoal.values.engine import Foreign
from moarcoal.values.model import Amount, NotYetComputable, Period, Unit, ValueKey, ValueRef
from moarcoal.values.testing import fixed
from moarcoal.web.helpers import capture_links
from moarcoal.web.links import document_url, site_url

MISSING_KEY = ValueKey("work.unknown")
CERTIFICATE_KEY = WAGE_TAX_CERTIFICATE.key


def state(*documents: Document) -> ModuleState:
    return ModuleState(State({d.address: d for d in documents}), WORK, "anna")


def certificate(year: int = 2025, owner: str = "anna") -> Document:
    return Document(
        owner=owner,
        site="Belege",
        path=f"lstb{year}.html",
        sha256="a" * 64,
        document_kind=CERTIFICATE_KEY,
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year, 12, 31),
    )


def keys(refs: list[ValueRef]) -> list[str]:
    return [r.key for r in refs]


# --- Fremde Schlüssel aus dem Ergebnis ------------------------------------------------------


def test_amount_names_the_used_foreign_key() -> None:
    value = tax_year(equipment())
    assert keys(foreign_refs(value(N_EQUIPMENT, YEAR))) == [WORK_EQUIPMENT]


def test_not_yet_computable_names_the_first_foreign_key_of_the_chain() -> None:
    foreign: Foreign = {**place(), (WORK_WORKDAYS, PLACE, YEAR): _not_yet}
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
    assert WORK.capture_url(WORK_EQUIPMENT, year, None, state()) == (
        "Arbeitsmittel erfassen (Arbeit)",
        "/arbeit?jahr=2025",
    )
    label, url = WORK.capture_url(WORK_WORKDAYS, year, PLACE, state()) or ("", "")
    assert label == "Erste Tätigkeitsstätte erfassen (Arbeit)"
    assert url == f"/arbeit/erste-taetigkeitsstaette/{PLACE.address.id}"
    assert WORK.capture_url(WORK_TRIP_DAYS, year, None, state()) == (
        "Dienstreisen erfassen (Arbeit)",
        "/arbeit?jahr=2025",
    )
    assert WORK.capture_url(MISSING_KEY, year, None, state()) is None


def test_capture_links_name_each_place_once() -> None:
    year = Period.year(2025)
    refs = [
        ValueRef(WORK_ABSENCE_DAYS, "anna", year, PLACE),
        ValueRef(WORK_HOMEOFFICE_DAYS, "anna", year, PLACE),
        ValueRef(WORK_TRIP_DAYS, "anna", year, None),
        ValueRef(GROSS_WAGES, "anna", year, None),
    ]
    links = capture_links(MODULES, State({}), "anna", refs)
    assert [label for label, _ in links] == [
        "Erste Tätigkeitsstätte erfassen (Arbeit)",
        "Dienstreisen erfassen (Arbeit)",
        "Lohnsteuerbescheinigung 2025 aufnehmen",
    ]


def test_wage_tax_keys_lead_to_taking_in_the_certificate() -> None:
    year = Period.year(2025)
    for key in (GROSS_WAGES, INCOME_TAX_WITHHELD, SOLI_WITHHELD, TAX_CLASS):
        assert WORK.capture_url(key, year, None, state()) == (
            "Lohnsteuerbescheinigung 2025 aufnehmen",
            "/belege?dokumentart=wage_tax_certificate&jahr=2025",
        )


def test_wage_tax_keys_lead_to_the_document_once_it_exists() -> None:
    document = certificate()
    found = WORK.capture_url(GROSS_WAGES, Period.year(2025), None, state(document))
    assert found == ("Lohnsteuerbescheinigung 2025 ansehen", document_url(document.id))


def test_other_year_or_other_user_does_not_count_as_taken_in() -> None:
    year = Period.year(2025)
    for other in (certificate(2024), certificate(2025, owner="berta")):
        label, _ = WORK.capture_url(GROSS_WAGES, year, None, state(other)) or ("", "")
        assert label == "Lohnsteuerbescheinigung 2025 aufnehmen"


def test_site_url_carries_kind_and_year() -> None:
    assert site_url() == "/belege"
    assert site_url(document_kind="x", year=2024) == "/belege?dokumentart=x&jahr=2024"


def test_belege_page_prefills_kind_and_year_of_the_address(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "lstb.html").write_text("x")
    client: httpx.Client = make_client(tmp_path / "daten", site)
    sha = hashlib.sha256(b"x").hexdigest()
    url = f"{site_url(document_kind=CERTIFICATE_KEY, year=2023)}&datei={sha}"
    page = client.get(url).text
    assert f'<option value="{CERTIFICATE_KEY}" selected>' in page
    assert 'name="year" value="2023"' in page
    # ohne Datei: Hinweis statt Formular, die Dateien der Liste behalten die Vorbelegung
    bare = client.get(site_url(document_kind=CERTIFICATE_KEY, year=2023)).text
    assert "Lohnsteuerbescheinigung" in bare.split("<main>")[1]
    assert f"datei={sha}&amp;dokumentart={CERTIFICATE_KEY}&amp;jahr=2023" in bare


def test_belege_page_ignores_unknown_kind_and_bad_year(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    (site / "lstb.html").write_text("x")
    client: httpx.Client = make_client(tmp_path / "daten", site)
    sha = hashlib.sha256(b"x").hexdigest()
    page = client.get(f"/belege?datei={sha}&dokumentart=gibtsnicht&jahr=abc").text
    assert "gibtsnicht" not in page


def test_page_links_the_certificate_next_to_the_gross_wages(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    client: httpx.Client = make_client(tmp_path / "daten", site)
    page = client.get("/steuerjahr/anlage-n/2025").text
    assert (
        '<a href="/belege?dokumentart=wage_tax_certificate&amp;jahr=2025">'
        "Lohnsteuerbescheinigung 2025 aufnehmen</a>"
    ) in page


# --- Seite ----------------------------------------------------------------------------------


def test_page_links_the_capture_next_to_the_amount(tmp_path: Path) -> None:
    site = tmp_path / "ablage"
    site.mkdir()
    client: httpx.Client = make_client(tmp_path / "daten", site)
    page = client.get("/steuerjahr/anlage-n/2025/10").text
    assert '<a href="/arbeit?jahr=2025">Arbeitsmittel erfassen (Arbeit)</a>' in page
