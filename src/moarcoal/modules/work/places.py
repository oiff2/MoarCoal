"""Orte der Dienstreisen und ihre Lage auf der Karte (#114): Eintragsart und reiner Fachkern.

Ein Startort ist der erste Ort einer Reise, jeder andere Ort der Reise ein Reiseziel, je Reise
einmal gezählt; ein am Ende noch einmal genannter Startort ist keines. Ein Ort kann beides
sein. Die Lage
eines Orts gilt für alle Jahre (sie steht nicht am Steuerjahr); ein Ort im Ausland oder ohne
Interesse wird als „nicht zeigen“ markiert. Ohne Netz und ohne Web: Stand rein, Änderungen raus.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from moarcoal.modules.work.entries import SCHEMA, TEXT_MAX, BusinessTrip
from moarcoal.modules.work.germany_map import GermanyMap
from moarcoal.storage import (
    Change,
    Delete,
    Entry,
    EntryAddress,
    EntryKind,
    Put,
    entry_checksum,
    entry_kind,
)

FOUND_AS_MAX = 500


class Place(Entry):
    """Ein Ort aus den Dienstreisen, wie er dort geschrieben steht, mit Lage oder „nicht zeigen“.

    Entweder hat der Ort eine Lage (Breite und Länge, dazu der Name des Treffers der Suche) oder er
    ist ausgeblendet, nie beides. Je Nutzer höchstens ein Eintrag je Ortsname.
    """

    name: str = Field(min_length=1, max_length=TEXT_MAX)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    found_as: str = Field(default="", max_length=FOUND_AS_MAX)
    hidden: bool = False

    @model_validator(mode="after")
    def _position_or_hidden(self) -> "Place":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Breite und Länge nur zusammen")
        if self.hidden == (self.latitude is not None):
            raise ValueError("Ein Ort hat entweder eine Lage oder ist ausgeblendet")
        return self


def check_place(entry: Place, entries: Mapping[EntryAddress, Entry]) -> str | None:
    """Schreibweg: je Nutzer und Ortsname höchstens ein Ort."""
    same = [
        e
        for e in entries.values()
        if isinstance(e, Place) and e.owner == entry.owner and e.name == entry.name
    ]
    return f"Für „{entry.name}“ gibt es schon einen Ort" if len(same) > 1 else None


def places_path(entry: Place) -> str:
    return f"users/{entry.owner}/work/places.json"


PLACE_KINDS: tuple[EntryKind, ...] = (entry_kind(Place, SCHEMA, places_path, check=check_place),)


@dataclass(frozen=True)
class PlaceUse:
    name: str
    is_start: bool
    destination_trips: int  # Reisen, die diesen Ort als Reiseziel haben


def place_uses(trips: Sequence[BusinessTrip]) -> list[PlaceUse]:
    """Die Orte der Reisen: Startorte zuerst (in Reihenfolge des Auftretens), dann Reiseziele."""
    starts: dict[str, None] = {}
    destinations: dict[str, int] = {}
    for trip in trips:
        start, *rest = trip.places
        starts[start] = None
        for name in dict.fromkeys(p for p in rest if p != start):
            destinations[name] = destinations.get(name, 0) + 1
    goals = sorted(
        (n for n in destinations if n not in starts), key=lambda n: (-destinations[n], n)
    )
    return [PlaceUse(name, name in starts, destinations.get(name, 0)) for name in [*starts, *goals]]


@dataclass(frozen=True)
class MapPoint:
    use: PlaceUse
    place: Place
    x: float
    y: float
    label_left: bool  # der Name steht links vom Punkt (nahe dem rechten Rand)

    @property
    def tooltip(self) -> str:
        parts = [self.use.name]
        if self.use.is_start:
            parts.append("Startort")
        if self.use.destination_trips:
            parts.append(trip_count_text(self.use.destination_trips))
        return " · ".join(parts)


@dataclass(frozen=True)
class MapPlaces:
    points: list[MapPoint]
    unplaced: list[PlaceUse]
    hidden: list[PlaceUse]


def trip_count_text(count: int) -> str:
    return f"{count} {'Fahrt' if count == 1 else 'Fahrten'}"


def sort_places(
    uses: Sequence[PlaceUse], places: Sequence[Place], germany: GermanyMap
) -> MapPlaces:
    """Auf der Karte, ohne Lage (zu suchen) oder nicht gezeigt; außerhalb der Karte = ohne Lage."""
    stored = {p.name: p for p in places}
    points: list[MapPoint] = []
    unplaced: list[PlaceUse] = []
    hidden: list[PlaceUse] = []
    for use in uses:
        place = stored.get(use.name)
        if place is not None and place.hidden:
            hidden.append(use)
            continue
        xy = None
        if place is not None and place.latitude is not None and place.longitude is not None:
            xy = germany.project(place.latitude, place.longitude)
        if place is None or xy is None:
            unplaced.append(use)
        else:
            left = xy[0] > germany.width * 0.62
            points.append(MapPoint(use, place, xy[0], xy[1], label_left=left))
    return MapPlaces(points, unplaced, hidden)


class PlaceError(Exception):
    """Die Lage lässt sich nicht speichern; der Text wird angezeigt."""


def _replacing(owner: str, name: str, existing: Place | None, **fields: object) -> Change:
    new = Place(owner=owner, name=name, **fields)  # pyright: ignore[reportArgumentType]
    if existing is None:
        return Put(new)
    return Put(new.model_copy(update={"id": existing.id}), entry_checksum(existing))


def locate_changes(
    owner: str,
    name: str,
    existing: Place | None,
    latitude: float,
    longitude: float,
    found_as: str,
    germany: GermanyMap,
) -> list[Change]:
    """Die Lage eines Orts setzen (ersetzt eine frühere Lage oder „nicht zeigen“)."""
    if germany.project(latitude, longitude) is None:
        raise PlaceError("Der Treffer liegt außerhalb der Karte von Deutschland.")
    fields = {"latitude": latitude, "longitude": longitude, "found_as": found_as[:FOUND_AS_MAX]}
    return [_replacing(owner, name, existing, **fields)]


def hide_changes(owner: str, name: str, existing: Place | None) -> list[Change]:
    """Den Ort nicht auf der Karte zeigen (z. B. im Ausland)."""
    return [_replacing(owner, name, existing, hidden=True)]


def forget_changes(existing: Place | None) -> list[Change]:
    """Lage oder „nicht zeigen“ vergessen: der Ort ist wieder ohne Lage."""
    return [] if existing is None else [Delete(existing.address, entry_checksum(existing))]
