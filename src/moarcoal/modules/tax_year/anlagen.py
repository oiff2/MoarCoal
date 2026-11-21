"""Die Anlagen des Steuerjahrs: Katalog und Struktur je Anlage und Jahr, Zuordnung zum Jahr.

Eine `Anlage` ist, was man für eine neue Anlage anmeldet: ihre Felder je Jahr (Katalog), ihre
Strukturen je Jahr und, wenn sie Werte berechnet, wie. Die Seiten und die drei Gegenproben kennen
nur diese Angaben. Eine Anlage, für die es im Jahr keine gespeicherte Struktur gibt, bekommt eine
vorläufige aus dem Übertragungsprotokoll des Jahrs; ihre Felder sind noch nicht berechenbar.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from moarcoal.modules.tax_year.entries import ProtocolReading
from moarcoal.modules.tax_year.fields import FormField, Forms, Rounding
from moarcoal.modules.tax_year.form_names import FORM_ORDER, form_name, form_rank
from moarcoal.modules.tax_year.structure import (
    FormPage,
    FormStructure,
    form_pages,
    provisional_structure,
)
from moarcoal.values.catalog import ValueDefinition
from moarcoal.values.model import ValueKey

type DefineValues = Callable[[Forms], tuple[ValueDefinition, ...]]
"""Die Werte, die eine Anlage aus ihrem Katalog berechnet (Werte des Moduls Arbeit u. a.)."""


def no_values(forms: Forms) -> tuple[ValueDefinition, ...]:
    return ()


@dataclass(frozen=True)
class Anlage:
    """Eine Anlage der Steuererklärung im Steuerjahr.

    `form` ist der Schlüssel wie im Übertragungsprotokoll (`N`, `KAP`, …). `forms` sind die Felder
    je Jahr, `structures` die gespeicherten Strukturen je Jahr, `define_values` macht aus dem
    Katalog die Werte der berechneten Felder (ohne: keine).
    """

    form: str
    forms: Forms
    structures: Mapping[int, FormStructure] = field(default_factory=dict[int, FormStructure])
    define_values: DefineValues = no_values

    @property
    def name(self) -> str:
        return form_name(self.form)

    @property
    def slug(self) -> str:
        """Der Teil der Adresse: `/steuerjahr/anlage-<slug>/<Jahr>`."""
        return self.form.lower()


@dataclass(frozen=True)
class YearAnlage:
    """Eine Anlage in einem Jahr, wie die Seite sie zeigt: Felder, Struktur, Seiten."""

    form: str
    slug: str
    name: str
    year: int
    fields: tuple[FormField, ...]
    structure: FormStructure
    pages: tuple[FormPage, ...]
    catalogued: bool  # eigener Katalog für das Jahr; ohne: die Felder der Struktur, unberechnet

    @property
    def provisional(self) -> bool:
        return self.structure.provisional


def field_catalog(anlagen: Iterable[Anlage], year: int) -> tuple[FormField, ...]:
    """Alle Felder des Jahrs über alle Anlagen."""
    return tuple(f for anlage in anlagen for f in anlage.forms.get(year, ()))


def uncatalogued_fields(structure: FormStructure) -> tuple[FormField, ...]:
    """Die Felder einer Anlage ohne Katalog, aus ihrer Struktur: nur Nr. und Bezeichnung, nichts
    wird berechnet."""
    return tuple(
        FormField(
            ValueKey(f"tax_year.{structure.form.lower()}_{described.e_kennung.lower()}"),
            described.e_kennung,
            described.line,
            described.label,
            None,
            Rounding.NONE,
            None,
            computed=False,
            form=structure.form,
        )
        for described in structure.fields
    )


def year_anlagen(
    anlagen: Sequence[Anlage], year: int, reading: ProtocolReading | None
) -> tuple[YearAnlage, ...]:
    """Die Anlagen, die das Jahr hat, in der Reihenfolge von Mein ELSTER.

    Das sind die angemeldeten Anlagen mit Katalog für das Jahr und, aus dem Übertragungsprotokoll
    des Jahrs, die weiteren der Formularliste. Eine Anlage ohne gespeicherte Struktur des Jahrs
    bekommt die vorläufige aus dem Protokoll; ohne Protokoll hat sie keine Seite.
    """
    lines = () if reading is None else reading.lines
    registered = {a.form: a for a in anlagen}
    forms = {a.form for a in anlagen if year in a.forms}
    forms |= {line.form for line in lines if line.form in FORM_ORDER}
    found: list[YearAnlage] = []
    for form in sorted(forms, key=form_rank):
        anlage = registered.get(form) or Anlage(form, {})
        structure = anlage.structures.get(year)
        if structure is None:
            structure = provisional_structure(form, year, lines)
        fields = anlage.forms.get(year)
        if fields is None:
            fields = uncatalogued_fields(structure)
        if not structure.fields or not fields:
            continue
        found.append(
            YearAnlage(
                form,
                anlage.slug,
                anlage.name,
                year,
                tuple(fields),
                structure,
                form_pages(structure, fields),
                year in anlage.forms,
            )
        )
    return tuple(found)


def protocol_contents(reading: ProtocolReading | None, structure: FormStructure) -> dict[str, str]:
    """Der Inhalt je E-Kennung der Anlage laut Protokoll, wie gedruckt und mit der Einheit des
    Felds aus der Struktur (das Protokoll druckt keine); mehrere Zeilen derselben E-Kennung
    stehen hintereinander."""
    units = {f.e_kennung: f.unit for f in structure.fields if f.unit}
    contents: dict[str, list[str]] = {}
    for line in () if reading is None else reading.lines:
        if line.form == structure.form:
            unit = units.get(line.elster_id)
            shown = f"{line.content} {unit}" if unit and line.content else line.content
            contents.setdefault(line.elster_id, []).append(shown)
    return {elster_id: "; ".join(found) for elster_id, found in contents.items()}
