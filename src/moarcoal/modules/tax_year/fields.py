"""Feld einer Anlage und seine Regeln: runden, anzeigen, Protokollfelder lesen, Abweichung nennen.

Die Werte der Felder sind gesetzlich gerundet, je nach Einheit und Richtung des Felds
(docs/recherche-runden-anlage-n.md). Welche Abweichung zugunsten des Steuerpflichtigen ist, leitet
das Feld aus derselben Angabe ab: bei Euro die Richtung, km zählen wie eine Ausgabe, Tage ohne.
"""

import dataclasses
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from moarcoal.modules.tax_year.entries import ElsterId, YearPersonInput
from moarcoal.modules.tax_year.form_names import form_name
from moarcoal.storage import PersonalDetails
from moarcoal.values.model import Amount, Unit, ValueKey, format_amount, parse_german_number


class Direction(StrEnum):
    """Richtung eines Euro-Felds: Einnahme oder Ausgabe; der Wert ist die Anzeige im Rechenweg."""

    INCOME = "Einnahme"
    EXPENSE = "Ausgabe"


class Rounding(StrEnum):
    """Wie der Wert eines Felds gerundet wird, bevor er einzutragen ist."""

    WHOLE_EUROS = "ganze Euro"  # zugunsten des Steuerpflichtigen, je nach Richtung
    EURO_CENTS = "Euro mit Cent"  # exakt
    WHOLE_KM = "volle km"  # abgerundet
    NONE = "ganzzahlig"  # Tage: schon ganzzahlig


NEW_FIELD = "neu"


@dataclass(frozen=True)
class TypedInput:
    """Ein Eintippfeld, das der Nutzer im Steuerjahr eingibt: genau einer der Texte `choices`, sonst
    freier Text, mit `day_range` ein Zeitraum im Jahr wie „01.01-31.12“. Werte, mit denen ein Modul
    rechnet, sind keine Eintippfelder, sondern Einträge dieses Moduls."""

    choices: tuple[str, ...] = ()
    day_range: bool = False

    def __post_init__(self) -> None:
        if self.choices and self.day_range:
            raise ValueError("Ein Zeitraum hat keine Auswahl.")

    def check(self, text: str, year: int) -> str | None:
        """Der Grund, warum `text` im Jahr `year` nicht passt; `None`, wenn er passt."""
        if self.choices:
            return None if text in self.choices else "Wähle eine der Möglichkeiten."
        if self.day_range and not _is_day_range(text, year):
            return f"Gib den Zeitraum als TT.MM-TT.MM an, Tage des Jahrs {year} in Reihenfolge."
        return None


_DAY_RANGE = re.compile(r"(\d{2})\.(\d{2})-(\d{2})\.(\d{2})")


def _is_day_range(text: str, year: int) -> bool:
    """Ob `text` zwei Tage des Jahrs als TT.MM-TT.MM nennt, der erste nicht nach dem zweiten."""
    match = _DAY_RANGE.fullmatch(text)
    if match is None:
        return False
    day1, month1, day2, month2 = (int(group) for group in match.groups())
    try:
        start, end = date(year, month1, day1), date(year, month2, day2)
    except ValueError:
        return False
    return start <= end


type PersonText = Callable[[PersonalDetails | None, YearPersonInput | None, int], str | None]
"""Der Text eines Felds aus den Angaben zur Person, der Eingabe zur Person im Jahr und dem Jahr;
`None`, wenn die Angabe fehlt."""


@dataclass(frozen=True)
class TextSource:
    """Woher ein Feld mit Text seinen Inhalt nimmt (Angaben zur Person oder Eingabe zur Person im
    Steuerjahr). `choices` sind die festen Optionen aus der Struktur, wenn das Feld eine Auswahl
    ist; die Eingabe muss dann eine davon sein."""

    read: PersonText
    choices: tuple[str, ...] = ()
    why_not: PersonText | None = None  # warum der Text trotz Angaben nicht berechenbar ist


@dataclass(frozen=True)
class AmbiguousLines:
    """Tage oder km stehen mehrfach im Protokoll; welche Zeile gilt, ist offen."""

    count: int


@dataclass(frozen=True)
class NotANumber:
    """Der Inhalt eines Protokollfelds ist keine Zahl."""

    content: str


@dataclass(frozen=True)
class FormField:
    """Ein Feld einer Anlage: Bezeichnung, E-Kennung (leer, solange unbekannt), Nr. im Vordruck.

    `key` ist der Schlüssel des Ausgewiesenen Werts, den das Steuerjahr dem Feld zuordnet. Der
    Katalog nimmt alle bekannten Felder des Jahrs auf, auch solche, die MoarCoal noch nicht
    berechnet (`computed` ist falsch: kein Wert, kein Schnappschuss) und solche ohne Betrag
    (`unit` ist leer: Text, Ja/Nein).

    `assessment` nennt die Positionen der Auslese-Vorlage des EStB, deren Summe
    dem Feld entspricht (leer: der EStB druckt das Feld nicht). `printed_rounded` heißt: der
    EStB druckt die Position in ganzen Euro, auch wo das Feld Cent hat.

    `typed` heißt: ein Eintippfeld, das der Nutzer im Steuerjahr eingibt (`TypedInput`).

    `text` heißt: ein Feld mit Text, dessen Inhalt MoarCoal aus der Person nimmt (`TextSource`);
    fehlt die Angabe, ist das Feld noch nicht berechenbar. Es hat weder Betrag noch Eintippfeld.

    `previous` ordnet das Feld dem Vorjahr zu, wo seine E-Kennung sich ändert: die E-Kennung des
    Vorjahrs oder `NEW_FIELD` (gibt es im Vorjahr nicht). Leer heißt: dieselbe E-Kennung wie im
    Vorjahr (`check_previous_years`).
    """

    key: ValueKey
    elster_id: ElsterId | None
    form_line: str
    label: str
    unit: Unit | None
    rounding: Rounding
    direction: Direction | None = None  # nur bei ganzen Euro
    computed: bool = True
    assessment: tuple[str, ...] = ()
    printed_rounded: bool = False
    previous: str | None = None
    typed: TypedInput | None = None
    text: TextSource | None = None
    form: str = dataclasses.field(kw_only=True)  # die Anlage, Schlüssel wie im Protokoll

    def __post_init__(self) -> None:
        if (self.rounding is Rounding.WHOLE_EUROS) != (self.direction is not None):
            raise ValueError(f"{self.label}: Richtung gehört genau zu Feldern mit ganzen Euro")
        if self.computed and self.unit is None:
            raise ValueError(f"{self.label}: ein berechnetes Feld braucht eine Einheit")
        if self.text is not None and (self.unit or self.computed or self.typed):
            raise ValueError(f"{self.label}: ein Feld mit Text hat keinen Betrag, keine Eingabe")
        if self.assessment and self.unit is None:
            raise ValueError(f"{self.label}: ein Feld ohne Betrag hat keine Position im EStB")

    @property
    def name(self) -> str:
        """Das Feld, wie Befunde es nennen: „Anlage N Nr. …, Bezeichnung“."""
        return f"{form_name(self.form)} Nr. {self.form_line}, {self.label}"

    @property
    def whole_euros(self) -> bool:
        """Ob das Feld ganze Euro nimmt (angezeigt ohne Cent)."""
        return self.rounding is Rounding.WHOLE_EUROS

    @property
    def _whole_numbers(self) -> bool:
        """Ob das Feld nur ganze Zahlen nimmt (Nachkommastellen heißen: ungerundet)."""
        return self.rounding is not Rounding.EURO_CENTS

    @property
    def _more_is_favourable(self) -> bool | None:
        """Ob ein höherer Wert zugunsten des Steuerpflichtigen ist; bei Tagen keine Aussage."""
        if self.direction is Direction.INCOME:
            return False
        if self.direction is Direction.EXPENSE or self.unit is Unit.KM:
            return True
        return None

    def round(self, value: Decimal) -> tuple[Decimal, str | None]:
        """Der einzutragende Wert und der Grund der Rundung; passt der Wert schon, kein Grund."""
        match self.rounding:
            case Rounding.WHOLE_EUROS:
                income = self.direction is Direction.INCOME
                rounded = value.to_integral_value(ROUND_FLOOR if income else ROUND_CEILING)
                reason = f"{'abgerundet' if income else 'aufgerundet'}, {self.direction}"
            case Rounding.WHOLE_KM:
                rounded = value.to_integral_value(ROUND_FLOOR)
                reason = "auf volle km abgerundet"
            case _:
                return value, None
        return (value, None) if rounded == value else (rounded, reason)

    def show(self, value: Decimal) -> str:
        """Wert deutsch mit Einheit, ganze Euro ohne Cent: '87 €', '86,40 €', '12 km'."""
        if self.unit is None:
            raise ValueError(f"{self.label}: ein Feld ohne Betrag hat keinen Wert zum Anzeigen")
        return format_amount(Amount(value, self.unit), whole_euros=self.whole_euros)

    def read_protocol(self, contents: Sequence[str]) -> Decimal | AmbiguousLines | NotANumber:
        """Der übertragene Wert aus den Inhalten der Protokollfelder dieses Felds (mindestens
        einer): Euro-Zeilen werden summiert, Tage und km sind mehrfach mehrdeutig."""
        if self.unit is not Unit.EUR and len(contents) > 1:
            return AmbiguousLines(len(contents))
        total = Decimal(0)
        for content in contents:
            number = parse_german_number(content)
            if number is None:
                return NotANumber(content)
            total += number
        return total

    def matches_assessment(self, frozen: Decimal, printed: Decimal) -> bool:
        """Ob der Betrag im EStB zum eingefrorenen Wert des Felds passt.

        Euro-Felder mit ganzen Euro und Positionen, die der EStB gerundet druckt, passen mit
        einer Spanne (ADR 0011 des Vorgängers): jeder ganze Euro zwischen abgerundetem und
        aufgerundetem Wert. Ein Feld mit ganzen Euro friert den schon nach seiner Richtung
        gerundeten Wert ein; der ungerundete liegt höchstens einen Euro daneben, die Spanne reicht
        deshalb von einem Euro darunter bis einen darüber. Sonst exakt. Das gedruckte Vorzeichen
        zählt nicht (Abzüge stehen mit Minus); Positionen mit Vorzeichen sind noch nicht zugeordnet.
        """
        frozen, printed = abs(frozen), abs(printed)
        if self.unit is not Unit.EUR or not (self.whole_euros or self.printed_rounded):
            return frozen == printed
        if printed != printed.to_integral_value():
            return False
        if self.whole_euros:
            return frozen - 1 <= printed <= frozen + 1
        return (
            frozen.to_integral_value(ROUND_FLOOR)
            <= printed
            <= frozen.to_integral_value(ROUND_CEILING)
        )

    def explain_deviation(self, expected: Decimal, transferred: Decimal) -> str:
        """Text der Abweichung; liegt sie nur an der Rundung, mit Differenz und Richtung."""
        shown = self.show(expected)
        plain = f"Wert {shown}, Protokoll {self.show(transferred)}."
        if not self._whole_numbers:
            return plain
        if transferred != transferred.to_integral_value():
            return f"nicht gerundet: {self.show(transferred)} statt {shown}."
        difference = transferred - expected
        favourable = self._more_is_favourable
        if abs(difference) > 1 or favourable is None:
            return plain
        how = "aufgerundet" if difference > 0 else "abgerundet"
        side = "Gunsten" if (difference > 0) == favourable else "Ungunsten"
        return f"um {self.show(abs(difference))} {how}, zu deinen {side} (Wert {shown})."


type Forms = Mapping[int, tuple[FormField, ...]]
"""Felder einer Anlage je Steuerjahr."""


def check_previous_years(forms: Mapping[int, Sequence[FormField]]) -> list[str]:
    """Strenge Vorjahres-Zuordnung: Probleme, wo ein Jahr nicht zum Vorjahr passt (leer: passt).

    Gibt es das Vorjahr, setzt jedes Feld die Zuordnung fort: dieselbe E-Kennung wie im Vorjahr,
    oder ausdrücklich `previous` (E-Kennung des Vorjahrs oder `NEW_FIELD`). Jedes Feld des
    Vorjahrs hat höchstens einen Nachfolger. Jahre ohne Vorjahr werden nicht geprüft.
    """
    problems: list[str] = []
    for year in sorted(forms):
        if year - 1 not in forms:
            continue
        before = {f.elster_id for f in forms[year - 1] if f.elster_id}
        claimed: dict[str, FormField] = {}
        for field in forms[year]:
            if field.elster_id is None or field.previous == NEW_FIELD:
                continue
            target = field.previous or field.elster_id
            where = f"{year}, {field.label} ({field.elster_id})"
            if target not in before:
                problems.append(
                    f"{where}: {target} gibt es {year - 1} nicht. "
                    f"Setze previous auf {NEW_FIELD!r} (neues Feld) oder die ersetzte E-Kennung."
                )
            elif target in claimed:
                problems.append(
                    f"{where}: verweist wie {claimed[target].elster_id} auf {target} "
                    f"von {year - 1}."
                )
            else:
                claimed[target] = field
    return problems
