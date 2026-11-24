"""Feld einer Anlage und seine Regeln: runden, anzeigen, Protokollfelder lesen, Abweichung nennen.

Die Werte der Felder sind gesetzlich gerundet, je nach Einheit und Richtung des Felds
(docs/recherche-runden-anlage-n.md). Welche Abweichung zugunsten des Steuerpflichtigen ist, leitet
das Feld aus derselben Angabe ab: bei Euro die Richtung, km zählen wie eine Ausgabe, Tage ohne.
"""

import dataclasses
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from moarcoal.modules.tax_year.entries import ElsterId, YearPersonInput
from moarcoal.modules.tax_year.form_names import form_name
from moarcoal.storage import PersonalDetails
from moarcoal.values.calculation import Calculation
from moarcoal.values.model import (
    Amount,
    LineItem,
    Unit,
    ValueKey,
    format_amount,
    parse_german_number,
)


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


type Compute = Callable[[Calculation, FormField], Amount]
"""Wie ein berechnetes Feld seinen Betrag rechnet: Rechnung und Feld (für Rundung und
Bezeichnung)."""


@dataclass(frozen=True)
class Computed:
    """Ein Feld mit Betrag, das MoarCoal aus Ausgewiesenen Werten berechnet: Einheit, Rundung,
    Richtung (nur bei ganzen Euro) und die Rechnung (`compute`).

    `assessment` nennt die Positionen der Auslese-Vorlage des EStB, deren Summe dem Feld entspricht
    (leer: der EStB druckt das Feld nicht). `printed_rounded` heißt: der EStB druckt die Position in
    ganzen Euro, auch wo das Feld Cent hat.
    """

    unit: Unit
    rounding: Rounding
    compute: Compute
    direction: Direction | None = None  # nur bei ganzen Euro
    assessment: tuple[str, ...] = ()
    printed_rounded: bool = False

    def __post_init__(self) -> None:
        if (self.rounding is Rounding.WHOLE_EUROS) != (self.direction is not None):
            raise ValueError("Richtung gehört genau zu Feldern mit ganzen Euro")

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


@dataclass(frozen=True)
class NotComputed:
    """Ein Feld, das MoarCoal noch nicht berechnet: kein Wert, kein Schnappschuss. Die Einheit zeigt
    die Struktur, die Richtung kommt mit der Rechnung."""


@dataclass(frozen=True)
class ItemizedAmount:
    """Eine Einzelangabe eines Felds mit Einzelangaben: Bezeichnung und der nach der Regel des
    Felds gerundete Betrag (nicht der ungerundete Einzelposten)."""

    label: str
    amount: Decimal

    @property
    def key(self) -> str:
        """Woran der Abgleich mit dem Protokoll sie erkennt: die Bezeichnung ohne
        Groß-/Kleinschreibung und ohne Leerraum."""
        return "".join(self.label.split()).casefold()


@dataclass(frozen=True)
class Itemized:
    """Ein Feld mit Einzelangaben („Einzelne Einträge“ in Mein ELSTER): unter `label_id`
    (Bezeichnung) und `amount_id` (Betrag) steht je Einzelangabe eine Zeile, die E-Kennung des
    Felds selbst gehört der Summe. `total` ist Einheit, Rundung, Richtung und Rechnung dieser
    Summe; seine Rechnung legt die Einzelposten an, jeder Einzelposten ist eine Einzelangabe."""

    label_id: ElsterId
    amount_id: ElsterId
    total: Computed

    def __post_init__(self) -> None:
        if self.total.unit is not Unit.EUR:
            raise ValueError("Einzelangaben haben Beträge in Euro")

    def amounts(self, items: Iterable[LineItem]) -> tuple[ItemizedAmount, ...]:
        """Die Einzelangaben zu den Einzelposten des Werts, je nach der Regel des Felds gerundet."""
        return tuple(
            ItemizedAmount(item.label, self.total.round(item.amount.value)[0]) for item in items
        )


type FieldKind = Computed | Itemized | TypedInput | TextSource | NotComputed
"""Die Art eines Felds; alles Übrige am Feld folgt aus ihr. Geschlossen: eine neue Art ist selten
und soll sichtbar sein (Pyright meldet jede Verzweigung, die sie nicht behandelt)."""


def amount_rule(kind: FieldKind) -> Computed | None:
    """Die Regel des Betrags eines Felds, das einen hat: bei `Itemized` die seiner Summe."""
    match kind:
        case Computed():
            return kind
        case Itemized():
            return kind.total
        case TypedInput() | TextSource() | NotComputed():
            return None


@dataclass(frozen=True)
class FieldMeaning:
    """Die Bedeutung eines Felds, eine Zeile im Katalog einer Anlage.

    `key` ist der Schlüssel des Ausgewiesenen Werts und steht ausdrücklich nur bei Feldern mit
    Betrag (`Computed`, `Itemized`); sonst leitet ihn `FormField.key` aus der E-Kennung ab.

    `previous` ordnet das Feld dem Vorjahr zu, wo seine E-Kennung sich ändert: die E-Kennung des
    Vorjahrs oder `NEW_FIELD` (gibt es im Vorjahr nicht). Leer heißt: dieselbe E-Kennung wie im
    Vorjahr (`check_previous_years`).
    """

    elster_id: ElsterId
    kind: FieldKind
    key: ValueKey | None = None
    previous: str | None = None

    def __post_init__(self) -> None:
        if (amount_rule(self.kind) is not None) != (self.key is not None):
            raise ValueError(
                f"{self.elster_id}: einen Schlüssel haben genau die berechneten Felder"
            )


@dataclass(frozen=True)
class FormField:
    """Ein Feld einer Anlage: seine Bedeutung aus dem Katalog, dazu Nr. im Vordruck und
    Bezeichnung aus der Struktur des Jahrs. `form` ist die Anlage, Schlüssel wie im Protokoll."""

    meaning: FieldMeaning
    form_line: str
    label: str
    form: str = dataclasses.field(kw_only=True)

    @property
    def elster_id(self) -> ElsterId:
        return self.meaning.elster_id

    @property
    def kind(self) -> FieldKind:
        return self.meaning.kind

    @property
    def previous(self) -> str | None:
        return self.meaning.previous

    @property
    def key(self) -> ValueKey:
        """Der Schlüssel des Felds: der des Katalogs, sonst aus Anlage und E-Kennung abgeleitet."""
        return self.meaning.key or ValueKey(
            f"tax_year.{self.form.lower()}_{self.meaning.elster_id.lower()}"
        )

    @property
    def computed(self) -> bool:
        """Ob MoarCoal das Feld berechnet (es hat dann einen Wert und einen Schnappschuss)."""
        return amount_rule(self.kind) is not None

    @property
    def itemized(self) -> Itemized | None:
        """Die Art `Itemized`, wenn das Feld Einzelangaben hat."""
        return self.kind if isinstance(self.kind, Itemized) else None

    @property
    def name(self) -> str:
        """Das Feld, wie Befunde es nennen: „Anlage N Nr. …, Bezeichnung“."""
        return f"{form_name(self.form)} Nr. {self.form_line}, {self.label}"

    @property
    def _computed(self) -> Computed:
        rule = amount_rule(self.kind)
        if rule is None:
            raise ValueError(f"{self.label}: ein Feld, das nicht berechnet wird, hat keinen Betrag")
        return rule

    @property
    def whole_euros(self) -> bool:
        """Ob das Feld ganze Euro nimmt (angezeigt ohne Cent)."""
        rule = amount_rule(self.kind)
        return rule is not None and rule.whole_euros

    def round(self, value: Decimal) -> tuple[Decimal, str | None]:
        """Der einzutragende Wert und der Grund der Rundung (Regel der Art `Computed`)."""
        return self._computed.round(value)

    def show(self, value: Decimal) -> str:
        return self._computed.show(value)

    def read_protocol(self, contents: Sequence[str]) -> Decimal | AmbiguousLines | NotANumber:
        return self._computed.read_protocol(contents)

    def matches_assessment(self, frozen: Decimal, printed: Decimal) -> bool:
        return self._computed.matches_assessment(frozen, printed)

    def explain_deviation(self, expected: Decimal, transferred: Decimal) -> str:
        return self._computed.explain_deviation(expected, transferred)


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
        before = {f.elster_id for f in forms[year - 1]}
        claimed: dict[str, FormField] = {}
        for field in forms[year]:
            if field.previous == NEW_FIELD:
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
