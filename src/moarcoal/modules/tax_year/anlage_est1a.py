"""Felder des Hauptvordrucks ESt 1 A 2025 und woher ihr Inhalt kommt.

Der Katalog nennt die Felder mit Text, die übrigen Felder der gespeicherten Struktur kommen als
`NotComputed` dazu. Ein Feld mit Text nimmt seinen Inhalt aus den Angaben zur Person oder aus der
Eingabe zur Person im Steuerjahr, so wie er in Mein ELSTER einzutragen ist (`TextSource`); fehlt
die Angabe, ist das Feld noch nicht berechenbar, nie leer. Alle anderen Felder hat MoarCoal noch
nicht. Beträge gibt es hier keine.
"""

import datetime
from collections.abc import Callable, Mapping

from moarcoal.modules.tax_year.anlagen import Anlage
from moarcoal.modules.tax_year.entries import YearPersonInput
from moarcoal.modules.tax_year.fields import FieldMeaning, TextSource
from moarcoal.modules.tax_year.structure import FormStructure, load_structure
from moarcoal.personal_details import religion_on
from moarcoal.storage import PersonalDetails, Religion

FORM = "ESt1A"  # Hauptvordruck ESt 1 A

IN_THIS_RETURN = "E0109814"  # Auswahl „In dieser Steuererklärung“
NO_ANSWER = "Keine Angabe"  # Option, die „nicht angegeben“ heißt
IBAN_DOMESTIC = "DE"  # die IBAN eines inländischen Geldinstituts beginnt damit

RELIGION_OPTION = {  # Option der Auswahl „Religion am 31.12.“ je Gemeinschaft
    Religion.NONE: "nicht kirchensteuerpflichtig",
    Religion.EVANGELICAL: "Evangelisch",
    Religion.ROMAN_CATHOLIC: "Römisch-katholisch",
    Religion.OLD_CATHOLIC: "Altkatholisch",
}

type DetailsText = Callable[[PersonalDetails, int], str | None]


def _details(
    read: DetailsText, choices: tuple[str, ...] = (), why_not: DetailsText | None = None
) -> TextSource:
    """Inhalt aus den Angaben zur Person (mit dem Jahr, wenn er davon abhängt)."""

    def reason(details: PersonalDetails | None, _: YearPersonInput | None, year: int) -> str | None:
        return None if details is None or why_not is None else why_not(details, year)

    return TextSource(
        lambda details, _, year: None if details is None else read(details, year),
        choices,
        reason if why_not is not None else None,
    )


def _year_input(read: Callable[[YearPersonInput], str | None], choices: tuple[str, ...] = ()):
    """Inhalt aus der Eingabe zur Person im Steuerjahr."""
    return TextSource(lambda _, entry, __: None if entry is None else read(entry), choices)


def _birth_date(details: PersonalDetails, year: int) -> str | None:
    return None if details.birth_date is None else details.birth_date.strftime("%d.%m.%Y")


def _religion_change(details: PersonalDetails, year: int) -> str | None:
    """Der Grund, warum die Religion nicht „ganzjährig gleichbleibend“ ist: eine Angabe im Jahr."""
    start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    if any(start < m.from_date <= end for m in details.religions):
        return f"Die Religionszugehörigkeit ändert sich {year} (Angaben zur Person)"
    return None


def _religion(details: PersonalDetails, year: int) -> str | None:
    if _religion_change(details, year) is not None:
        return None
    religion = religion_on(details, datetime.date(year, 12, 31))
    return None if religion is None else RELIGION_OPTION[religion]


def _iban(domestic: bool) -> DetailsText:
    def read(details: PersonalDetails, year: int) -> str | None:
        iban = details.iban
        return iban if iban is not None and iban.startswith(IBAN_DOMESTIC) == domestic else None

    return read


def sources(structure: FormStructure) -> Mapping[str, TextSource]:
    """Die Felder mit Text und ihre Quelle; die Optionen der Auswahlen aus der Struktur."""
    return {
        "E0100008": _year_input(lambda i: i.phone),
        "E0100081": _details(lambda d, y: d.id_number),
        "E0100401": _details(_birth_date),
        "E0100201": _details(lambda d, y: d.last_name),
        "E0100301": _details(lambda d, y: d.first_name),
        "E0101004": _details(lambda d, y: d.title),
        "E0101104": _details(lambda d, y: d.street),
        "E0101206": _details(lambda d, y: d.house_number),
        "E0100601": _details(lambda d, y: d.postal_code),
        "E0100602": _details(lambda d, y: d.city),
        "E0100403": _year_input(lambda i: i.occupation),
        "E0100402": _details(_religion, structure.get("E0100402").options, _religion_change),
        "E0102102": _details(_iban(domestic=True)),
        "E0102603": _details(_iban(domestic=False)),
        IN_THIS_RETURN: _year_input(
            lambda i: i.in_this_return,
            tuple(o for o in structure.get(IN_THIS_RETURN).options if o != NO_ANSWER),
        ),
    }


def catalog_2025(structure: FormStructure) -> tuple[FieldMeaning, ...]:
    """Die Felder mit Text und ihre Quelle; die übrigen Felder der Struktur kommen als
    `NotComputed` dazu (`all_structure_fields`)."""
    return tuple(
        FieldMeaning(elster_id, source) for elster_id, source in sources(structure).items()
    )


ANLAGE_EST1A = Anlage(
    FORM, {2025: catalog_2025(load_structure(FORM, 2025))}, all_structure_fields=True
)
