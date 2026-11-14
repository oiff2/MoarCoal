"""Vorbelegen des Aufnehmen-Formulars aus dem Datei- und Ordnernamen (docs/grundgeruest.md, 6).

Feste Regeln, bei jeder Anfrage berechnet, nichts gespeichert. Ein Treffer gilt nur, wenn er
eindeutig ist: mehrere Aussteller, mehrere Jahre oder mehrere Dokumentarten belegen nichts vor.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from moarcoal.defaults import MAX_YEAR, MIN_YEAR
from moarcoal.documents import DocumentKind
from moarcoal.storage import Issuer, State, name_key

MIN_NAME_LENGTH = 3  # kürzere Namen und Aliasse träfen zu oft zufällig
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)|(?<!\d)(20\d\d)(?:0[1-9]|1[0-2])[0-3]\d(?!\d)")


@dataclass(frozen=True)
class Prefill:
    """Was aus dem Namen eindeutig folgt; `None` heißt: nichts vorbelegen."""

    issuer: Issuer | None = None
    year: int | None = None
    kind: str | None = None


def _words(text: str) -> str:
    """Vergleichsform für Pfade: `name_key`, Trenner (`_`, `-`, `/`, `.`) werden zu Leerzeichen."""
    return " ".join(re.findall(r"[^\W_]+", name_key(text)))


def _issuer(state: State, text: str) -> Issuer | None:
    padded = f" {_words(text)} "
    found = [
        i
        for i in state.of_kind(Issuer)
        if any(
            len(name_key(n)) >= MIN_NAME_LENGTH and f" {_words(n)} " in padded
            for n in (i.name, *i.aliases)
        )
    ]
    return found[0] if len(found) == 1 else None


def _year(text: str) -> int | None:
    years = {int(m.group(1) or m.group(2)) for m in _YEAR.finditer(text)}
    years = {y for y in years if MIN_YEAR <= y <= MAX_YEAR}
    return years.pop() if len(years) == 1 else None


def _kind(kinds: Iterable[DocumentKind], text: str) -> str | None:
    words = _words(text)
    found = [
        k.key for k in kinds if any(re.search(p, words, re.IGNORECASE) for p in k.name_patterns)
    ]
    return found[0] if len(found) == 1 else None


def prefill_from_name(state: State, kinds: Iterable[DocumentKind], path: str) -> Prefill:
    """Aussteller, Jahr und Dokumentart aus dem Pfad der Datei (Ordner und Dateiname)."""
    return Prefill(_issuer(state, path), _year(path), _kind(kinds, path))
