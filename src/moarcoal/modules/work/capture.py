"""Wo man erfasst, woraus die Werte von Arbeit rechnen (`ModuleRegistration.capture_url`, #180)."""

from moarcoal.modules.work.trips import values as trips
from moarcoal.modules.work.workplace import values as workplace
from moarcoal.modules.work.workplace.forms import entry_url
from moarcoal.values.model import Period, Subject, TimeRef, ValueKey

_WORKPLACE = {
    workplace.WORKDAYS,
    workplace.DISTANCE_KM,
    workplace.WORKDAYS_PER_WEEK,
    workplace.ABSENCE_DAYS,
    workplace.CAR_DISTANCE_KM,
    workplace.HOMEOFFICE_DAYS,
}
_TRIPS = {trips.TRIP_DAYS, trips.TRAVEL_FARE, trips.TRAVEL_TOTAL}


def capture_url(key: ValueKey, time: TimeRef, subject: Subject | None) -> tuple[str, str] | None:
    """Beschriftung und Adresse der Erfassung; mit Bezugsobjekt dessen Eintrag (offen), sonst die
    Seite von Arbeit im Jahr. Werte aus der Lohnsteuerbescheinigung: noch keine (#181)."""
    if key == workplace.EQUIPMENT:
        label = "Arbeitsmittel erfassen (Arbeit)"
    elif key in _WORKPLACE:
        label = "Erste Tätigkeitsstätte erfassen (Arbeit)"
    elif key in _TRIPS:
        label = "Dienstreisen erfassen (Arbeit)"
    else:
        return None
    url = entry_url(subject.address) if subject is not None else None
    if url is None:
        year = time.start.year if isinstance(time, Period) else time.day.year
        url = f"/arbeit?jahr={year}"
    return label, url
