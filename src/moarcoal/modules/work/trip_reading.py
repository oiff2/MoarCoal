"""Dienstreisen aus Screenshots: Auslese-Vorlage und Übernahme eines Vorschlags (#113).

Fachkern ohne Web und ohne Speicher. Ein Screenshot ist ein Dokument der Dokumentart
„Reiseaufstellung“; Claude liest ihn über den gemeinsamen Aufrufbaustein nach `TEMPLATE` aus, das
Ergebnis ist ein Vorschlag (`Proposal`) mit einer Zelle je Spalte und Reise. Hier wird der Vorschlag
als Tabelle aufbereitet (`proposed_trips`) und die Übernahme zu Änderungen für `apply` gerechnet
(`take_over_changes`): die Reisen und die Bestätigung ihrer Felder in einem Vorgang. Geparst und
geprüft wird mit den Regeln der Dienstreisen-Tabelle (`trips.validate_row`).
"""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from moarcoal.documents import DocumentKind
from moarcoal.extraction_template import ExtractionTemplate, TemplateField, row_key, split_row_key
from moarcoal.modules.work.entries import BusinessTrip
from moarcoal.modules.work.trips import TripRow, validate_row
from moarcoal.storage import Content, Document, Proposal, Put

TRIP_STATEMENT_KEY = "trip_statement"  # Schlüssel der Dokumentart
ROWS = "trips"
START, END, PLACES, KM, UNSURE = "start", "end", "places", "km", "unsure"
IGNORED = "ignored_columns"
CELLS = (START, END, PLACES, KM)  # Spalten, die eine Reise ausmachen
COLUMNS = (*CELLS, UNSURE)

TEMPLATE = ExtractionTemplate(
    1,
    (
        TemplateField(
            IGNORED,
            "Ausgelassene Spalten",
            hint="Überschriften von Spalten oder Beträgen, die du gesehen, aber nicht als Reise-km "
            "gemeldet hast, weil sie keine Kilometer sind (z. B. Tagespauschale, Verpflegung, "
            "Übernachtung, Spesen, Erstattung), mit Komma getrennt; leer, wenn es keine gab. "
            "Solche Beträge nie als km melden.",
        ),
    ),
    ROWS,
    (
        TemplateField(
            START,
            "Start",
            hint="Erster Tag der Reise als JJJJ-MM-TT; ein Datum ohne Jahr gilt im Steuerjahr "
            "der Aufstellung; leer, wenn nicht ablesbar",
        ),
        TemplateField(
            END,
            "Ende",
            hint="Letzter Tag als JJJJ-MM-TT; leer bei einer eintägigen Reise oder wenn nicht "
            "ablesbar",
        ),
        TemplateField(
            PLACES,
            "Orte",
            hint="Orte in der besuchten Reihenfolge, mit „ → “ getrennt, der Rückweg als letzter "
            "Ort, wenn die Aufstellung ihn zeigt (z. B. A → B → A); Namen wie gezeigt, ohne "
            "Anschrift und Postleitzahl",
        ),
        TemplateField(
            KM,
            "km",
            "km",
            "Kilometer der ganzen Reise mit dem Pkw als ganze Zahl; werden nur die Kilometer "
            "je Teilstrecke gezeigt, addiere sie; leer, wenn keine Kilometer gezeigt werden",
        ),
        TemplateField(
            UNSURE,
            "Unsicher",
            hint="Die Felder dieser Reise (start, end, places, km), die du nicht sicher lesen "
            "konntest (unscharf, abgeschnitten, mehrdeutig), mit Komma getrennt; leer, wenn alle "
            "sicher sind",
        ),
    ),
    "Reise",
)

STATEMENT = DocumentKind(
    key=TRIP_STATEMENT_KEY,
    title="Reiseaufstellung (Screenshot)",
    has_period=True,
    read_in=lambda document, content: [],  # wird nur ausgelesen, nicht eingelesen
    extraction_template=TEMPLATE,
)


@dataclass
class ProposedTrip:
    """Eine Reise des Vorschlags, wie die Tabelle sie zeigt."""

    number: int
    row: TripRow
    year: int  # Jahr der Reise (ihr Start), nicht das der Aufstellung
    uncertain: frozenset[str] = frozenset()
    taken: bool = False  # alle Felder der Reise sind bestätigt
    out_of_year: bool = False
    duplicate: bool = False
    errors: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def takeable(self) -> bool:
        return not self.taken and not self.errors

    @property
    def preselected(self) -> bool:
        return self.takeable and not (self.out_of_year or self.duplicate or self.uncertain)


def _text(content: Content) -> str:
    return "" if content is None else str(content).strip()


def _km(content: Content) -> tuple[str, str]:
    """km als Text für die Zeile und ein Fehler, wenn der Inhalt keine ganze Zahl ist."""
    spec = next(f for f in TEMPLATE.row_fields if f.key == KM)
    try:
        number = spec.read(content)
    except ValueError:
        return _text(content), "km sind keine Zahl."
    if number is None:
        return "", ""
    if not isinstance(number, Decimal) or number != number.to_integral_value():
        return _text(content), "km sind keine ganze Zahl."
    return str(int(number)), ""


def _start_year(text: str, default: int) -> int:
    try:
        return datetime.date.fromisoformat(text).year
    except ValueError:
        return default


def _numbers(proposal: Proposal) -> list[int]:
    cells = (split_row_key(key) for key in proposal.fields)
    return sorted({cell[1] for cell in cells if cell and cell[0] == ROWS})


def proposed_trips(
    proposal: Proposal, year: int, existing: Sequence[BusinessTrip]
) -> list[ProposedTrip]:
    """Die Reisen des Vorschlags mit Markierungen: Fehler (auch fehlende km), unsicher, mögliche
    Dublette (gleiches Startdatum wie eine gespeicherte Reise), außerhalb des Jahrs `year`.

    Eine Reise außerhalb des Jahrs gilt für das Jahr ihres Starts (die Dienstreise gehört zu genau
    einem Steuerjahr).
    """
    found: list[ProposedTrip] = []
    for number in _numbers(proposal):
        keys = {c: key for c in COLUMNS if (key := row_key(ROWS, number, c)) in proposal.fields}
        contents: dict[str, Content] = {c: proposal.fields[k].content for c, k in keys.items()}

        km, km_error = _km(contents.get(KM))
        row = TripRow(
            start=_text(contents.get(START)),
            end=_text(contents.get(END)),
            places=_text(contents.get(PLACES)),
            km=km,
        )
        trip_year = _start_year(row.start, year)
        trip = validate_row(row, trip_year, proposal.owner)
        errors = dict(row.errors)
        if km_error:
            errors["km"] = km_error
        unsure = {part.strip() for part in _text(contents.get(UNSURE)).split(",")}
        found.append(
            ProposedTrip(
                number=number,
                row=row,
                year=trip_year,
                uncertain=frozenset(unsure & set(CELLS)),
                taken=all(proposal.fields[key].confirmed for key in keys.values()),
                out_of_year=trip_year != year,
                duplicate=trip is not None
                and any(t.year == trip.year and t.start == trip.start for t in existing),
                errors=errors,
            )
        )
    return found


def take_over_changes(
    proposal: Proposal,
    year: int,
    selected: set[int],
    owner: str,
    existing: Sequence[BusinessTrip],
    checksum: str,
) -> tuple[list[Put], dict[int, str]]:
    """Die Änderungen, die die Übernahme der gewählten Reisen verlangt, oder Fehler je Reise.

    Je gewählter, noch nicht übernommener Reise eine Dienstreise (aus dem, was gilt: Korrektur
    oder Ausgelesenes) und die Bestätigung ihrer Felder am Vorschlag, dazu die ausgelassenen Spalten
    als gesehen; alles in einem Vorgang. Ohne km keine Übernahme. Ist eine gewählte Reise nicht
    übernehmbar, wird nichts übernommen.
    """
    proposed = {p.number: p for p in proposed_trips(proposal, year, existing)}
    problems: dict[int, str] = {}
    changes: list[Put] = []
    fields = dict(proposal.fields)
    for number in sorted(selected):
        item = proposed.get(number)
        if item is None or item.taken:
            problems[number] = "Diese Reise gibt es nicht oder sie ist schon übernommen."
            continue
        trip = None if item.errors else validate_row(item.row, item.year, owner)
        if trip is None:
            problems[number] = " ".join((item.errors or item.row.errors).values())
            continue
        changes.append(Put(trip))
        for column in COLUMNS:
            key = row_key(ROWS, number, column)
            if key in fields:
                fields[key] = fields[key].model_copy(update={"confirmed": True})
    if problems or not changes:
        return [], problems
    if IGNORED in fields:
        fields[IGNORED] = fields[IGNORED].model_copy(update={"confirmed": True})
    changed = proposal.model_copy(update={"fields": fields})
    return [*changes, Put(changed, expected=checksum)], {}


def statements(documents: Sequence[Document], year: int) -> list[Document]:
    """Die Aufstellungen des Jahrs, ältestes zuerst."""
    found = [d for d in documents if d.document_kind == TRIP_STATEMENT_KEY and d.touches_year(year)]
    return sorted(found, key=lambda d: (d.taken_in_at, d.id))
