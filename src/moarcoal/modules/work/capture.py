"""Wo man erfasst, woraus die Werte von Arbeit rechnen (`ModuleRegistration.capture_url`, #180)."""

from moarcoal.modules.work.trips import values as trips
from moarcoal.modules.work.wage_tax import values as wage_tax
from moarcoal.modules.work.wage_tax.reading import WAGE_TAX_CERTIFICATE
from moarcoal.modules.work.workplace import values as workplace
from moarcoal.modules.work.workplace.forms import entry_url
from moarcoal.registration import ModuleState
from moarcoal.values.model import Period, Subject, TimeRef, ValueKey
from moarcoal.web.links import document_url, site_url

_WORKPLACE = {
    workplace.WORKDAYS,
    workplace.DISTANCE_KM,
    workplace.WORKDAYS_PER_WEEK,
    workplace.ABSENCE_DAYS,
    workplace.CAR_DISTANCE_KM,
    workplace.HOMEOFFICE_DAYS,
}
_CERTIFICATE = {definition.entry.key for definition in wage_tax.VALUES}  # Werte aus dem Beleg
_TRIPS = {trips.TRIP_DAYS, trips.TRAVEL_FARE, trips.TRAVEL_TOTAL}


def _year_of(time: TimeRef) -> int:
    return time.start.year if isinstance(time, Period) else time.day.year


def _certificate(time: TimeRef, state: ModuleState) -> tuple[str, str]:
    """Werte aus der Lohnsteuerbescheinigung: Gibt es sie für das Jahr schon, zum Dokument, sonst
    zum Aufnehmen auf der Belege-Seite (Dokumentart und Jahr vorbelegt)."""
    year = _year_of(time)
    document = next(
        (d for d in state.documents(WAGE_TAX_CERTIFICATE.key) if d.touches_year(year)), None
    )
    if document is not None:
        return f"Lohnsteuerbescheinigung {year} ansehen", document_url(document.id)
    url = site_url(document_kind=WAGE_TAX_CERTIFICATE.key, year=year)
    return f"Lohnsteuerbescheinigung {year} aufnehmen", url


def capture_url(
    key: ValueKey, time: TimeRef, subject: Subject | None, state: ModuleState
) -> tuple[str, str] | None:
    """Beschriftung und Adresse der Erfassung; mit Bezugsobjekt dessen Eintrag (offen), sonst die
    Seite von Arbeit im Jahr. Werte aus der Lohnsteuerbescheinigung führen zum Beleg."""
    if key in _CERTIFICATE:
        return _certificate(time, state)
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
        url = f"/arbeit?jahr={_year_of(time)}"
    return label, url
