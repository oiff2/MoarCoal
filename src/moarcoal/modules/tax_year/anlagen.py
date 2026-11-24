"""Die Anlagen des Steuerjahrs: Katalog je Jahr, daraus abgeleitet Felder, Struktur und Werte.

Eine `Anlage` ist, was man für eine neue Anlage anmeldet: ihren Katalog je Jahr, eine Folge von
Bedeutungen der Felder (`FieldMeaning`). Strukturen, Felder und die Werte der berechneten Felder
folgen daraus. Die Seiten und die drei Gegenproben kennen nur diese Ableitung. Eine Anlage, für die
es im Jahr keine gespeicherte Struktur gibt, bekommt eine vorläufige aus dem Übertragungsprotokoll
des Jahrs; ihre Felder sind noch nicht berechenbar.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from moarcoal.modules.tax_year.entries import ProtocolReading
from moarcoal.modules.tax_year.fields import (
    Computed,
    FieldMeaning,
    FormField,
    Itemized,
    NotComputed,
    amount_rule,
)
from moarcoal.modules.tax_year.form_names import FORM_ORDER, form_name, form_rank
from moarcoal.modules.tax_year.special_parts import SpecialPart
from moarcoal.modules.tax_year.structure import (
    DIRECTORY,
    FormPage,
    FormStructure,
    form_pages,
    load_structure,
    provisional_structure,
)
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, ValueKey


def derive_fields(
    form: str,
    structure: FormStructure,
    meanings: Iterable[FieldMeaning],
    *,
    all_structure_fields: bool,
) -> tuple[FormField, ...]:
    """Die Felder einer Anlage in einem Jahr: je Bedeutung des Katalogs das Feld mit Nr. und
    Bezeichnung aus der Struktur. Mit `all_structure_fields` kommen die übrigen Felder der Struktur
    als `NotComputed` dazu, und alle folgen der Reihenfolge der Struktur. Eine E-Kennung, die die
    Struktur nicht kennt, ist ein Fehler (`UnknownElsterId`)."""
    named = {m.elster_id: m for m in meanings}
    wanted = [structure.get(elster_id) for elster_id in named]
    absorbed = {  # Bezeichnung und Betrag der Einzelangaben: das Feld ist die Summe
        structure.get(elster_id).e_kennung
        for m in named.values()
        if isinstance(m.kind, Itemized)
        for elster_id in (m.kind.label_id, m.kind.amount_id)
    }
    if all_structure_fields:
        wanted = [f for f in structure.fields if f.e_kennung not in absorbed]
    return tuple(
        FormField(
            named.get(described.e_kennung) or FieldMeaning(described.e_kennung, NotComputed()),
            described.line,
            described.label,
            form=form,
        )
        for described in wanted
    )


@dataclass(frozen=True)
class Anlage:
    """Eine Anlage der Steuererklärung im Steuerjahr.

    `form` ist der Schlüssel wie im Übertragungsprotokoll (`N`, `KAP`, …). `catalogs` sind die
    Bedeutungen ihrer Felder je Jahr (der Katalog). Die Anlage lädt für jedes dieser Jahre die
    Struktur aus `structure_directory` und leitet daraus `fields` und die Werte der berechneten
    Felder (`values`) ab. Mit `all_structure_fields` nimmt sie auch die Felder der Struktur auf,
    die der Katalog nicht nennt (als `NotComputed`). `parts` sind ihre Sonderteile (was
    die Seite außer den Feldern zeigt). Ein Jahr mit leerem Katalog hat eine
    Struktur, aber keinen Katalog (`YearAnlage.catalogued` ist dann falsch).
    """

    form: str
    catalogs: Mapping[int, Sequence[FieldMeaning]] = field(
        default_factory=dict[int, Sequence[FieldMeaning]]
    )
    all_structure_fields: bool = False
    parts: tuple[SpecialPart, ...] = ()
    structure_directory: Path = DIRECTORY
    structures: Mapping[int, FormStructure] = field(init=False, repr=False, compare=False)
    fields: Mapping[int, tuple[FormField, ...]] = field(init=False, repr=False, compare=False)
    values: tuple[ValueDefinition, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        structures = {
            year: load_structure(self.form, year, self.structure_directory)
            for year in self.catalogs
        }
        fields = {
            year: derive_fields(
                self.form,
                structures[year],
                meanings,
                all_structure_fields=self.all_structure_fields,
            )
            for year, meanings in self.catalogs.items()
        }
        object.__setattr__(self, "structures", structures)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "values", self._values())

    @property
    def name(self) -> str:
        return form_name(self.form)

    @property
    def slug(self) -> str:
        """Der Teil der Adresse: `/steuerjahr/anlage-<slug>/<Jahr>`."""
        return self.form.lower()

    def _values(self) -> tuple[ValueDefinition, ...]:
        """Ein Wert je berechnetes Feld, das in einem der Jahre vorkommt; die Bezeichnung aus dem
        jüngsten Jahr. Felder, die MoarCoal noch nicht berechnet, haben keinen Wert."""
        latest: dict[ValueKey, tuple[FormField, Computed]] = {}
        for year in sorted(self.fields):
            for each in self.fields[year]:
                if (rule := amount_rule(each.kind)) is not None:
                    latest[each.key] = (each, rule)

        def definition(key: ValueKey, described: FormField, kind: Computed) -> ValueDefinition:
            def calculate(calculation: Calculation) -> Amount:
                year = calculation.year
                mine = next((f for f in self.fields.get(year, ()) if f.key == key), None)
                rule = None if mine is None else amount_rule(mine.kind)
                if mine is None or rule is None:
                    calculation.not_yet(f"{self.name} {year} deckt MoarCoal noch nicht ab")
                return rule.compute(calculation, mine)

            return ValueDefinition(
                CatalogEntry(
                    key,
                    f"{self.name}, {described.label}",
                    described.label,
                    kind.unit,
                    TimeKind.PERIOD,
                ),
                calculate,
            )

        return tuple(definition(key, f, kind) for key, (f, kind) in latest.items())


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
    parts: tuple[SpecialPart, ...] = ()

    @property
    def provisional(self) -> bool:
        return self.structure.provisional


def field_catalog(anlagen: Iterable[Anlage], year: int) -> tuple[FormField, ...]:
    """Alle Felder des Jahrs über alle Anlagen."""
    return tuple(f for anlage in anlagen for f in anlage.fields.get(year, ()))


def year_anlagen(
    anlagen: Sequence[Anlage], year: int, reading: ProtocolReading | None
) -> tuple[YearAnlage, ...]:
    """Die Anlagen, die das Jahr hat, in der Reihenfolge von Mein ELSTER.

    Das sind die angemeldeten Anlagen mit Katalog für das Jahr und, aus dem Übertragungsprotokoll
    des Jahrs, die weiteren der Formularliste. Eine Anlage ohne gespeicherte Struktur des Jahrs
    bekommt die vorläufige aus dem Protokoll; ohne Protokoll hat sie keine Seite. Ohne Katalog
    sind alle Felder der Struktur noch nicht berechnet.
    """
    lines = () if reading is None else reading.lines
    registered = {a.form: a for a in anlagen}
    forms = {a.form for a in anlagen if a.catalogs.get(year)}
    forms |= {line.form for line in lines if line.form in FORM_ORDER}
    found: list[YearAnlage] = []
    for form in sorted(forms, key=form_rank):
        anlage = registered.get(form) or Anlage(form)
        structure = anlage.structures.get(year)
        if structure is None:
            structure = provisional_structure(form, year, lines)
        fields = anlage.fields.get(year)
        if fields is None:
            fields = derive_fields(form, structure, (), all_structure_fields=True)
        if not structure.fields or not fields:
            continue
        found.append(
            YearAnlage(
                form,
                anlage.slug,
                anlage.name,
                year,
                fields,
                structure,
                form_pages(structure, fields),
                bool(anlage.catalogs.get(year)),
                anlage.parts,
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
