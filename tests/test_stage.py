"""Stufe einer Zeile und darüber (#248): die Regeln, Statusstreifen und Baum sagen dasselbe.

Die Regeln prüfen `grade_row` und `combine` an erfundenen Ergebnissen; der Zusammenhang von Seite
und Baum läuft über die gerenderte Seite einer erfundenen Anlage KAP.
"""

import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app_helper import make_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_anlage_view import KAP, ORIGIN, PORT, USER, YEAR, line, protocol
from test_anlage_view import client as kap_client

from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import registration
from moarcoal.modules.tax_year.field_checks import FieldCheck
from moarcoal.modules.tax_year.protocol_check import DEVIATION
from moarcoal.modules.tax_year.stage import Grading, Reason, Stage, combine, grade_row
from moarcoal.storage import EntryAddress, Put
from moarcoal.values.findings import Severity
from moarcoal.values.model import (
    Amount,
    ExpectedDocumentLocator,
    ExposedValue,
    LineItem,
    NotApplicable,
    NotYetComputable,
    Period,
    UserInputLocator,
    ValueKey,
    ValueResult,
    Workings,
)

KEY = ValueKey("tax_year.kap_demo")
TIME = Period.year(YEAR)
ADDRESS = EntryAddress(kind="Expense", id="7KQ2M3XA4T")


def amount(locator: ExpectedDocumentLocator | UserInputLocator | None) -> ExposedValue:
    euros = Amount(Decimal(10), Amount.eur_cents(0).unit)
    items = () if locator is None else (LineItem("Posten", euros, locator),)
    return ExposedValue(KEY, USER, TIME, None, euros, items, Workings(()))


PROVEN = amount(None)
ASSUMED = amount(UserInputLocator(ADDRESS))
EXPECTED = amount(ExpectedDocumentLocator(ADDRESS))
NOT_YET = NotYetComputable(KEY, USER, TIME, None, "Es fehlt eine Angabe")
NOT_APPLICABLE = NotApplicable(KEY, USER, TIME, None, "trifft nicht zu")
FITS = FieldCheck("Laut Protokoll", "10,00 €", fits=True)


def deviates(severity: Severity | None) -> FieldCheck:
    return FieldCheck("Laut Protokoll", "9,00 €", deviation="weicht ab", severity=severity)


@pytest.mark.parametrize(
    ("result", "checks", "stage"),
    [
        (None, (), Stage.NONE),  # kein Eintrag, nichts offen: kein Punkt
        (NOT_APPLICABLE, (), Stage.NONE),
        (PROVEN, (), Stage.GOOD),  # belegt
        (None, (FITS,), Stage.GOOD),  # eine passende Gegenprobe
        (ASSUMED, (), Stage.OPEN),  # nicht belegter Betrag
        (EXPECTED, (), Stage.OPEN),  # erwarteter Beleg fehlt
        (NOT_YET, (), Stage.OPEN),  # nicht mehr rot
        (PROVEN, (deviates(Severity.NOTE),), Stage.OPEN),  # Hinweis
        (PROVEN, (deviates(Severity.WARNING),), Stage.OPEN),  # Warnung
        (None, (deviates(None),), Stage.OPEN),  # Abweichung ohne Schweregrad
        (PROVEN, (deviates(Severity.ERROR),), Stage.ERROR),  # abweichende Gegenprobe, Fehler
        (NOT_YET, (deviates(Severity.ERROR),), Stage.ERROR),  # rot vor gelb
        (EXPECTED, (FITS,), Stage.OPEN),  # gelb vor grün
    ],
)
def test_the_stage_of_a_row(
    result: ValueResult | None, checks: tuple[FieldCheck, ...], stage: Stage
) -> None:
    assert grade_row(result, checks, filled=False).stage is stage


def test_a_hidden_deviation_counts_for_nothing() -> None:
    hidden = FieldCheck(
        "Laut Protokoll", "9,00 €", deviation="weicht ab", severity=Severity.ERROR, hidden=True
    )
    assert grade_row(None, (hidden,), filled=False).stage is Stage.NONE
    assert grade_row(PROVEN, (hidden,), filled=False).stage is Stage.GOOD
    assert grade_row(EXPECTED, (hidden,), filled=False).stage is Stage.OPEN


def test_a_filled_input_or_text_without_a_fitting_check_is_open() -> None:
    assert grade_row(None, (), filled=True).stage is Stage.OPEN
    assert grade_row(None, (), filled=True).title == "1 Angabe nicht belegt"
    assert grade_row(None, (FieldCheck("Laut Protokoll", "–"),), filled=True).stage is Stage.OPEN
    assert grade_row(None, (FITS,), filled=True).stage is Stage.GOOD  # passende Gegenprobe
    assert grade_row(None, (), filled=False).stage is Stage.NONE  # leer, nichts offen
    assert grade_row(None, (deviates(Severity.ERROR),), filled=True).stage is Stage.ERROR


def test_the_reasons_are_counted_and_named_for_the_tooltip() -> None:
    graded = grade_row(EXPECTED, (deviates(Severity.NOTE),), filled=False)

    assert graded.reasons == ((Reason.NOTE, 1), (Reason.EXPECTED, 1))
    assert graded.title == "1 Hinweis, 1 Beleg erwartet"
    assert grade_row(NOT_YET, (), filled=False).title == "1 Feld noch nicht berechenbar"
    assert grade_row(PROVEN, (), filled=False).title == "belegt oder passt, nichts offen"
    assert grade_row(None, (), filled=False).title == ""


def test_the_worst_stage_of_the_parts_wins_and_the_reasons_add_up() -> None:
    parts = [
        grade_row(PROVEN, (), filled=False),
        grade_row(EXPECTED, (deviates(Severity.NOTE),), filled=False),
        grade_row(EXPECTED, (), filled=False),
    ]

    above = combine(parts)

    assert above.stage is Stage.OPEN
    assert above.title == "1 Hinweis, 2 Belege erwartet"
    assert (
        combine([*parts, grade_row(None, (deviates(Severity.ERROR),), filled=False)]).stage
        is Stage.ERROR
    )
    assert (
        combine([grade_row(PROVEN, (), filled=False), grade_row(None, (FITS,), filled=False)]).stage
        is Stage.GOOD
    )
    assert combine([]) == Grading()


# --- Statusstreifen und Baum sagen dasselbe ----------------------------------------------------


def stripes(page: str) -> set[str]:
    return set(re.findall(r'<tr class="(streifen-\w+)" id="feld-', page))


def tree_dot(page: str, href_end: str) -> str:
    """Das Wort (und der Grund) des Punkts hinter dem Link `href_end` im Baum, sonst ``."""
    tree = page.split('class="anlagen-baum"')[1].split("</nav>")[0]
    link = (
        rf'href="[^"]*{re.escape(href_end)}"[^>]*>[^<]*(?:</a>)?(?:\s*<small[^>]*>[^<]*</small>)?'
    )
    found = re.search(link + r'<span class="status [^"]*" title="([^"]*)"', tree)
    return "" if found is None else found.group(1)


def test_the_strip_and_the_tree_agree_for_the_page_and_the_anlage(tmp_path: Path) -> None:
    http = kap_client(tmp_path)

    page = http.get("/steuerjahr/anlage-kap/2025").text

    # Das berechnete Feld Z. 6 ist noch nicht berechenbar: gelb im Streifen, nicht rot
    assert "streifen-warnung" in stripes(page) and "streifen-fehler" not in stripes(page)
    expected = "offen: 1 Feld noch nicht berechenbar"
    assert tree_dot(page, "/steuerjahr/anlage-kap/2025/10") == expected
    assert tree_dot(page, "/steuerjahr/anlage-kap/2025") == expected


def test_the_overview_carries_the_dots_too(tmp_path: Path) -> None:
    page = kap_client(tmp_path).get("/steuerjahr").text

    assert tree_dot(page, "/steuerjahr/anlage-kap/2025").startswith("offen:")


def test_the_dot_is_never_colour_alone(tmp_path: Path) -> None:
    page = kap_client(tmp_path).get("/steuerjahr").text

    assert re.search(r'<span class="nur-vorlesen">offen: 1 Feld noch nicht berechenbar<', page)
    assert 'aria-hidden="true">▲<' in page


def test_a_filled_input_is_yellow_in_the_strip_and_in_the_tree(tmp_path: Path) -> None:
    http = kap_client(tmp_path)
    http.post("/steuerjahr/person/2025", data={"occupation": "Gärtner"}, headers=ORIGIN)

    page = http.get("/steuerjahr/anlage-kap/2025").text

    row = re.search(r'<tr class="(streifen-\w+)" id="feld-E0900002"', page)
    assert row is not None and row.group(1) == "streifen-warnung"
    assert "1 Angabe nicht belegt" in tree_dot(page, "/steuerjahr/anlage-kap/2025/10")
    empty = re.search(r'<tr class="(streifen-\w+)" id="feld-E0900001"', page)
    assert empty is not None and empty.group(1) == "streifen-still"


def web(app: FastAPI) -> httpx.Client:
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_a_hidden_finding_counts_neither_in_the_strip_nor_in_the_tree(tmp_path: Path) -> None:
    modules = [registration((KAP,)) if m.key == "tax_year" else m for m in MODULES]
    app = make_app(PORT, tmp_path, modules, user=USER)
    for entry in protocol(line("E0900005", "9,00")):
        app.state.store.apply([Put(entry)])
    http = web(app)
    money = r'<tr class="(streifen-\w+)" id="feld-E0900005"'
    page = http.get("/steuerjahr/anlage-kap/2025").text
    assert re.search(money, page).group(1) == "streifen-warnung"  # type: ignore[union-attr]
    assert "1 Warnung" in tree_dot(page, "/steuerjahr/anlage-kap/2025")

    forms = re.findall(
        r'<form id="ausblenden[^>]*>(.*?)</form>', http.get("/befunde?jahr=2025").text, re.S
    )
    fields = [dict(re.findall(r'name="(\w+)" value="([^"]*)"', f)) for f in forms]
    (mine,) = [f for f in fields if f["kind"] == DEVIATION]
    http.post("/befunde/ausblenden", data={**mine, "note": "Geklärt."}, headers=ORIGIN)

    page = http.get("/steuerjahr/anlage-kap/2025").text
    assert "Warnung" not in tree_dot(page, "/steuerjahr/anlage-kap/2025")
    again = re.search(money, page)
    assert (
        again is not None and again.group(1) == "streifen-gut"
    )  # belegter Betrag; die ausgeblendete Abweichung färbt nicht
    assert "weicht ab" in page  # die Gegenprobe zeigt die Abweichung weiter
