"""Formulare der ersten Tätigkeitsstätte und der Arbeitsmittel: Felder prüfen und vorbelegen.

Die Hinweise je Feld nennen die Grenzen der Modelle (`workplace.entries`), nicht eigene Zahlen.
"""

from collections.abc import Callable

from moarcoal.defaults import DEFAULT_YEAR, MAX_YEAR, MIN_YEAR
from moarcoal.modules.work.common import TEXT_MAX
from moarcoal.modules.work.workplace.entries import (
    DAYS_PER_WEEK,
    DEFAULT_WORKDAYS,
    MAX_ABSENCE_DAYS,
    MAX_DISTANCE_KM,
    MAX_WORKDAYS,
    FirstWorkplace,
    UserInput,
    WorkEquipment,
)
from moarcoal.storage import Entry, EntryAddress
from moarcoal.values.model import parse_cents
from moarcoal.web.helpers import validated

type Fields = dict[str, str]
type Build = Callable[[Fields, str, str], tuple[Entry | None, list[str]]]

# Hinweis je Feld, wenn die Prüfung es ablehnt (Pydantic liefert nur englische Meldungen).
HINTS = {
    "year": f"Steuerjahr: Jahr zwischen {MIN_YEAR} und {MAX_YEAR}",
    "workdays": f"Arbeitstage: ganze Zahl von 0 bis {MAX_WORKDAYS}",
    "distance_km": f"Einfache Entfernung: ganze Zahl von 0 bis {MAX_DISTANCE_KM} km",
    "workdays_per_week": f"Arbeitstage je Woche: ganze Zahl von 1 bis {DAYS_PER_WEEK}, oder leer",
    "absence_days": f"Urlaubs- und Krankheitstage: ganze Zahl von 0 bis {MAX_ABSENCE_DAYS}, "
    "oder leer",
    "car_distance_km": "Mit dem Pkw gefahrene km: ganze Zahl, höchstens die einfache Entfernung, "
    "oder leer",
    "description": f"Beschreibung: höchstens {TEXT_MAX} Zeichen",
    "amount_cents": "Betrag: größer als 0, mit höchstens zwei Nachkommastellen, z. B. 49,90",
    "date": "Datum: gültiges Datum",
}
EQUIPMENT_HINTS = {**HINTS, "description": f"Beschreibung: angeben, höchstens {TEXT_MAX} Zeichen"}

OPTIONAL_WORKPLACE = ("workdays_per_week", "absence_days", "car_distance_km")


def build_workplace(fields: Fields, owner: str, entry_id: str) -> tuple[Entry | None, list[str]]:
    return validated(
        FirstWorkplace,
        {
            "id": entry_id,
            "owner": owner,
            "year": fields.get("year", ""),
            "workdays": fields.get("workdays", ""),
            "distance_km": fields.get("distance_km", ""),
            "description": fields.get("description", "").strip(),
            **{name: fields.get(name, "").strip() or None for name in OPTIONAL_WORKPLACE},
        },
        HINTS,
    )


def build_equipment(fields: Fields, owner: str, entry_id: str) -> tuple[Entry | None, list[str]]:
    cents = parse_cents(fields.get("amount", ""))  # None: die Prüfung unten meldet den Betrag
    user_input, errors = validated(
        UserInput,
        {
            "amount_cents": cents,
            "date": fields.get("date", ""),
            "description": fields.get("description", "").strip(),
        },
        EQUIPMENT_HINTS,
    )
    if user_input is None:
        return None, errors
    return validated(
        WorkEquipment,
        {
            "id": entry_id,
            "owner": owner,
            "year": fields.get("year", ""),
            "input": user_input.model_dump(),
        },
        EQUIPMENT_HINTS,
    )


class EntryForm:
    def __init__(self, slug: str, title: str, model: type[Entry], build: Build) -> None:
        self.slug = slug
        self.title = title
        self.model = model
        self.build = build


KINDS = {
    "erste-taetigkeitsstaette": EntryForm(
        "erste-taetigkeitsstaette", "Erste Tätigkeitsstätte", FirstWorkplace, build_workplace
    ),
    "arbeitsmittel": EntryForm("arbeitsmittel", "Arbeitsmittel", WorkEquipment, build_equipment),
}


def entry_url(address: EntryAddress) -> str | None:
    """Link zur Änderungsseite eines Eintrags des Moduls, sonst `None`."""
    for kind in KINDS.values():
        if kind.model.__name__ == address.kind:
            return f"/arbeit/{kind.slug}/{address.id}"
    return None


def prefill_new(slug: str) -> Fields:
    """Vorbelegung eines neuen Formulars."""
    if slug == "erste-taetigkeitsstaette":
        return {"year": str(DEFAULT_YEAR), "workdays": str(DEFAULT_WORKDAYS)}
    return {"year": str(DEFAULT_YEAR)}


def prefill_from(entry: Entry | None) -> Fields:
    """Vorbelegung der Formularfelder aus einem Eintrag."""
    match entry:
        case FirstWorkplace():
            return {
                "year": str(entry.year),
                "workdays": str(entry.workdays),
                "distance_km": str(entry.distance_km),
                "description": entry.description,
                **{
                    name: "" if getattr(entry, name) is None else str(getattr(entry, name))
                    for name in OPTIONAL_WORKPLACE
                },
            }
        case WorkEquipment():
            euros, cents = divmod(entry.input.amount_cents, 100)
            return {
                "year": str(entry.year),
                "amount": f"{euros},{cents:02d}",
                "date": entry.input.date.isoformat(),
                "description": entry.input.description,
            }
        case _:
            return {"year": str(DEFAULT_YEAR)}
