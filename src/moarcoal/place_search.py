"""Ortssuche auf Klick: Nominatim (OpenStreetMap), nur wenn der Nutzer „Suchen“ drückt (#114).

Nur der getippte Suchtext verlässt den Rechner: keine Reise, kein Datum, kein Steuerjahr. Die Suche
ist auf Deutschland beschränkt, es geht höchstens eine Anfrage je Sekunde hinaus (Nutzungsregel von
Nominatim), und der User-Agent nennt die App allgemein, ohne Kontaktdaten. Die Seiten bekommen eine
`PlaceSearch` über `app.state`; Tests geben einen Fake mit und berühren nie das Netz (ADR 0008).
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "MoarCoal/0.1 (local tax preparation tool)"
MIN_INTERVAL_SECONDS = 1.0
MAX_RESULTS = 6
TIMEOUT_SECONDS = 15


class PlaceSearchError(Exception):
    """Die Suche ging nicht (offline, abgewiesen, unlesbare Antwort); der Text wird angezeigt."""


@dataclass(frozen=True)
class PlaceHit:
    name: str  # Anzeigename, z. B. "Musterstadt, Beispielkreis, Bayern, Deutschland"
    state: str  # das Bundesland, leer wenn die Antwort keines nennt
    latitude: float
    longitude: float


class PlaceSearch(Protocol):
    def search(self, text: str) -> list[PlaceHit]: ...


type Fetch = Callable[[urllib.request.Request], bytes]


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


class NominatimSearch:
    """Die echte Suche. `fetch`, `clock` und `sleep` lassen sich für Tests ersetzen."""

    def __init__(
        self,
        fetch: Fetch = _fetch,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._fetch, self._clock, self._sleep = fetch, clock, sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def search(self, text: str) -> list[PlaceHit]:
        query = urllib.parse.urlencode(
            {
                "q": text,
                "countrycodes": "de",
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": MAX_RESULTS,
                "accept-language": "de",
            }
        )
        request = urllib.request.Request(
            f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT}
        )
        with self._lock:  # eine Anfrage je Sekunde, über alle Threads
            if self._last is not None:
                wait = MIN_INTERVAL_SECONDS - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            try:
                body = self._fetch(request)
            except (urllib.error.URLError, OSError) as error:
                reason = getattr(error, "reason", error)
                raise PlaceSearchError(f"Die Ortssuche ist nicht erreichbar: {reason}") from None
        return _parse(body)


def _address(item: dict[str, Any]) -> dict[str, Any]:
    address = item.get("address")
    return cast(dict[str, Any], address) if isinstance(address, dict) else {}


def _parse(body: bytes) -> list[PlaceHit]:
    try:
        answer: list[dict[str, Any]] = json.loads(body)
        return [
            PlaceHit(
                name=str(item["display_name"]),
                state=str(_address(item).get("state", "")),
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
            )
            for item in answer
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise PlaceSearchError("Die Antwort der Ortssuche ist nicht lesbar.") from None


class FakePlaceSearch:
    """Fake für Tests: liefert vorgegebene Treffer oder einen Fehler und merkt sich die Texte."""

    def __init__(self, hits: Sequence[PlaceHit] = (), error: str = "") -> None:
        self.hits, self.error = list(hits), error
        self.asked: list[str] = []

    def search(self, text: str) -> list[PlaceHit]:
        self.asked.append(text)
        if self.error:
            raise PlaceSearchError(self.error)
        return list(self.hits)
