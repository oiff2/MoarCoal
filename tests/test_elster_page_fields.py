"""Tests for tools/elster_page_fields.py with a made-up page in Mein-ELSTER markup."""

import elster_page_fields as epf

PAGE = """
<html><body>
<h1 data-ipe-type="Page.title">2 - Einnahmen</h1>
<h2>Mieteinnahmen <span>Hilfe zum Begriff anzeigen</span></h2>
<h3>Mieteinnahmen für Wohnungen</h3>
<div data-node-type="InlineMzb">
  <label for="X(0)_fields(eruVEinnWhgEinzE0700201)">Mieteinnahmen<em> (Euro)</em></label>
  <input name="fields[eruVEinnWhgEinzE0700201]" value="999">
</div>
<div class="formItem" data-node-type="Line">
  <div class="formItem__lnr" title="Zeile 15"><span>Zeile &nbsp;</span> 15</div>
  <label for="Startseite(0)_X(0)_fields(eruVEinnWhgSumE0700206)">Summe<em> (Euro)</em></label>
  <input name="fields[eruVEinnWhgSumE0700206]" value="1234">
  <input name="fieldsResetSource[eruVEinnWhgSumE0700206]" type="hidden" value="false">
</div>
<h2>Nutzung</h2>
<div class="formItem" data-node-type="Line">
  <div class="formItem__lnr" title="Zeile 10">10</div>
  <div class="formItem__wrapper" role="group" aria-label="als Ferienwohnung genutzt">
    <input name="fields[eruVAllgNutzungE0700703]" type="radio" value="true">
    <label for="Startseite(0)_X(0)_fields(eruVAllgNutzungE0700703)_0">Ja</label>
    <input name="fields[eruVAllgNutzungE0700703]" type="radio" value="false">
    <label for="Startseite(0)_X(0)_fields(eruVAllgNutzungE0700703)_1">Nein</label>
  </div>
</div>
<div data-node-type="Line">
  <label for="Startseite(0)_X(0)_fields(eruVOhneZeileE0709901)">Hinweis vorhanden.Ohne Zeile</label>
</div>
<input name="fields[eruVOhneKennung]">
</body></html>
"""


def test_reads_kennung_zeile_label_and_headings_once_per_field():
    fields = epf.read_page(PAGE)

    assert [(f.e_kennung, f.line, f.label) for f in fields] == [
        ("E0700201", "", "Mieteinnahmen (Euro)"),
        ("E0700206", "15", "Summe (Euro)"),
        ("E0700703", "10", "als Ferienwohnung genutzt"),
        ("E0709901", "", "Ohne Zeile"),
    ]
    assert fields[1].headings == ("2 - Einnahmen", "Mieteinnahmen", "Mieteinnahmen für Wohnungen")
    assert fields[2].headings == ("2 - Einnahmen", "Nutzung")


def test_output_names_the_field_but_never_a_value():
    output = "\n".join(epf.format_fields(epf.read_page(PAGE)))

    assert "## 2 - Einnahmen / Mieteinnahmen / Mieteinnahmen für Wohnungen" in output
    assert "  Z   15 | E0700206 | eruVEinnWhgSum | Summe (Euro)" in output
    assert "1234" not in output
    assert "999" not in output
