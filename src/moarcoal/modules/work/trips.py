"""Dienstreisen-Tabelle: Zellen als getippt, rein gerechnet zu Änderungen für `apply`.

Fachkern ohne Web und ohne Speicher: Der Stand der Reisen und die Zellen des Formulars gehen
hinein, eine Liste von Änderungen (`Put`, `Delete`) oder deutsche Fehlermeldungen je Zelle kommen
heraus. Zellen heißen `<Spalte>-<N>`:

    start-N, ende-N   TT.MM.JJJJ, TT.MM.JJ, TT.MM. (Jahr des Steuerjahrs) oder JJJJ-MM-TT
    orte-N            Orte in Reihenfolge, getrennt mit „→“, „->“, „;“ oder „ - “
    km-N              km der ganzen Reise, ganze Zahl über 0
    notiz-N           frei
    id-N, pruefsumme-N  die Reise, die die Zeile zeigt (leer bei einer neuen Zeile)
    loeschen-N        „ja“ löscht die Zeile beim Speichern
    zeilen            Anzahl der Zeilen

Eine Zeile ohne Daten, km und Notiz und mit höchstens einem Ort (dem vorbelegten Startort) ist
leer: eine neue wird übergangen, eine gespeicherte gelöscht.
"""

import datetime
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError

from moarcoal.modules.work.entries import BusinessTrip, TripsConfirmation, trips_fingerprint
from moarcoal.storage import Delete, Put, entry_checksum, new_id
from moarcoal.values.model import Amount, Unit

PLACE_SEPARATOR = " → "
_PLACE_SPLIT = re.compile(r"\s*(?:→|->|;|\s-\s)\s*")
_GERMAN_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MAX_ROWS = 2000

# Kilometersatz je Steuerjahr in Euro je km (Anleitung zur Anlage N 2025, Reisekosten, Nr. 66).
KM_RATES: Mapping[int, Decimal] = {2025: Decimal("0.30")}


class TripTableError(Exception):
    """Mindestens eine Zeile ist ungültig; die Zeilen tragen ihre Fehler."""


@dataclass
class TripRow:
    start: str = ""
    end: str = ""
    places: str = ""
    km: str = ""
    note: str = ""
    entry_id: str = ""
    checksum: str = ""
    delete: bool = False
    amount: Amount | None = None  # km × Satz einer gespeicherten Reise, zum Anzeigen
    errors: dict[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def from_trip(cls, trip: BusinessTrip, rate: Decimal | None) -> "TripRow":
        return cls(
            start=trip.start.isoformat(),
            end=trip.end.isoformat() if trip.end else "",
            places=format_places(trip.places),
            km=str(trip.distance_km),
            note=trip.note,
            entry_id=trip.id,
            checksum=entry_checksum(trip),
            amount=None if rate is None else Amount(km_amount(trip.distance_km, rate), Unit.EUR),
        )

    @property
    def is_blank(self) -> bool:
        return (
            not (self.start or self.end or self.km or self.note)
            and len(split_places(self.places)) <= 1
        )


def format_places(places: Sequence[str]) -> str:
    return PLACE_SEPARATOR.join(places)


def split_places(text: str) -> list[str]:
    return [p for p in _PLACE_SPLIT.split(text.strip()) if p]


def km_amount(km: int, rate: Decimal) -> Decimal:
    """km × Satz in Euro, auf den Cent genau (ein halber Cent rundet auf)."""
    return (Decimal(km) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sorted_trips(trips: Sequence[BusinessTrip]) -> list[BusinessTrip]:
    return sorted(trips, key=lambda t: (t.start, t.id))


def place_prefill(trips: Sequence[BusinessTrip]) -> str:
    """Orte einer neuen Zeile: der Startort der letzten Reise, bereit für das Ziel."""
    return f"{sorted_trips(trips)[-1].places[0]}{PLACE_SEPARATOR}" if trips else ""


def rows_from_form(data: Mapping[str, str]) -> list[TripRow]:
    try:
        count = min(int(data.get("zeilen", "0")), MAX_ROWS)
    except ValueError:
        count = 0

    def get(name: str, n: int) -> str:
        return data.get(f"{name}-{n}", "").strip()

    return [
        TripRow(
            start=get("start", n),
            end=get("ende", n),
            places=get("orte", n),
            km=get("km", n),
            note=get("notiz", n),
            entry_id=get("id", n),
            checksum=get("pruefsumme", n),
            delete=get("loeschen", n) == "ja",
        )
        for n in range(count)
    ]


def validate_row(row: TripRow, year: int, owner: str) -> BusinessTrip | None:
    """Die Zeile als Reise, oder `None` mit `row.errors` je Spalte; Daten werden zu JJJJ-MM-TT."""
    errors = row.errors
    errors.clear()
    start = _date(row.start, year, "start", errors, required=True)
    end = _date(row.end, year, "ende", errors, required=False)
    if start:
        row.start = start.isoformat()
    if end:
        row.end = end.isoformat()
    if start and end and end < start:
        errors["ende"] = "Ende liegt vor dem Start."
    places = split_places(row.places)
    if len(places) < 2:
        errors["orte"] = "Mindestens zwei Orte, Rückweg ausdrücklich (z. B. A → B → A)."
    km = None
    if not row.km:
        errors["km"] = "km fehlen."
    elif not (row.km.isascii() and row.km.isdigit()) or int(row.km) == 0:
        errors["km"] = f"„{row.km}“ ist keine ganze Zahl über 0."
    else:
        km = int(row.km)
    if errors or start is None or km is None:
        return None
    try:
        return BusinessTrip(
            id=row.entry_id or new_id(),
            owner=owner,
            year=year,
            start=start,
            end=end,
            places=tuple(places),
            distance_km=km,
            note=row.note,
        )
    except (
        ValidationError
    ) as error:  # Grenzen (Länge, km-Obergrenze), die oben nicht einzeln stehen
        columns = {"distance_km": "km", "note": "notiz", "places": "orte"}
        for problem in error.errors():
            errors[columns.get(str(problem["loc"][-1]) if problem["loc"] else "", "start")] = (
                "Eingabe zu lang oder zu groß."
            )
        return None


def _date(
    text: str, year: int, name: str, errors: dict[str, str], *, required: bool
) -> datetime.date | None:
    label = "Start" if name == "start" else "Ende"
    if not text:
        if required:
            errors[name] = f"{label} fehlt."
        return None
    try:
        if match := _GERMAN_DATE.match(text):
            day, month, given = match.groups()
            full = int(given) + 2000 if given and len(given) == 2 else int(given) if given else year
            value = datetime.date(full, int(month), int(day))
        elif match := _ISO_DATE.match(text):
            value = datetime.date(*(int(g) for g in match.groups()))
        else:
            raise ValueError(text)
    except ValueError:
        errors[name] = f"{label} „{text}“ ist kein Datum (TT.MM.JJJJ)."
        return None
    if value.year != year:
        errors[name] = f"{label} {value:%d.%m.%Y} liegt nicht im Steuerjahr {year}."
    return value


def plan_changes(
    rows: Sequence[TripRow], year: int, owner: str, existing: Sequence[BusinessTrip]
) -> list[Put | Delete]:
    """Die Änderungen, die die Tabelle gegenüber dem Stand verlangt; ein ungültiges Feld: Fehler.

    Unveränderte Zeilen ergeben nichts. Eine geänderte oder gelöschte Reise trägt die Prüfsumme,
    die das Formular zeigte (ein zwischenzeitlicher Stand weist `apply` ab).
    """
    known = {t.id: t for t in existing}
    changes: list[Put | Delete] = []
    failed = False
    for row in rows:
        stored = known.get(row.entry_id) if row.entry_id else None
        if row.entry_id and stored is None:
            row.errors = {"start": "Diese Reise gibt es nicht mehr; Seite neu laden."}
            failed = True
            continue
        if stored is not None and (row.delete or row.is_blank):
            changes.append(Delete(stored.address, row.checksum))
            continue
        if row.delete or row.is_blank:
            continue
        trip = validate_row(row, year, owner)
        if trip is None:
            failed = True
        elif trip != stored:
            changes.append(Put(trip, expected=row.checksum if stored else None))
    if failed:
        raise TripTableError("Bitte die markierten Zellen korrigieren.")
    return changes


def current_confirmation(
    confirmations: Sequence[TripsConfirmation], trips: Sequence[BusinessTrip]
) -> TripsConfirmation | None:
    """Die Bestätigung, die für genau den heutigen Stand der Reisen gilt; sonst `None`."""
    fingerprint = trips_fingerprint(list(trips))
    return next((c for c in confirmations if c.trips_fingerprint == fingerprint), None)


def confirm_changes(
    confirmations: Sequence[TripsConfirmation],
    trips: Sequence[BusinessTrip],
    year: int,
    owner: str,
    today: datetime.date,
) -> list[Put]:
    """Bestätigt den heutigen Stand der Reisen; eine ältere Bestätigung wird ersetzt."""
    new = TripsConfirmation(
        owner=owner,
        year=year,
        confirmed_on=today,
        trips_fingerprint=trips_fingerprint(list(trips)),
    )
    if not confirmations:
        return [Put(new)]
    old = confirmations[0]
    return [Put(new.model_copy(update={"id": old.id}), expected=entry_checksum(old))]
