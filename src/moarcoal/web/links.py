"""Adressen der Seiten zu den Bausteinen der Datenebene (die Datenebene kennt keine Routen).

Wer außerhalb einer Routen-Angabe eine Adresse braucht (Befund, Seitenleiste, Vorschau), baut sie
hier; der Testkern weist Routen in `storage/` und `values/` ab.
"""

from collections.abc import Iterable
from urllib.parse import urlencode

from moarcoal.document_filter import SearchFilter


def _filter_pairs(query: str, types: Iterable[str]) -> list[tuple[str, str]]:
    pairs = [("suche", query.strip())] if query.strip() else []
    return pairs + [("typ", value) for value in types]


def with_filter(url: str, search: SearchFilter) -> str:
    """Die Adresse `url` mit Suche und Dateitypen der Belege-Seite (vor dem `#`), damit sie beim
    Navigieren und nach Formularen stehen bleiben; ohne aktiven Filter unverändert."""
    pairs = _filter_pairs(search.query, sorted(t.value for t in search.types))
    if not pairs:
        return url
    base, hash_, fragment = url.partition("#")
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}{urlencode(pairs)}{hash_}{fragment}"


def site_url(
    *,
    document_kind: str | None = None,
    year: int | None = None,
    query: str = "",
    types: Iterable[str] = (),
    file: str | None = None,
) -> str:
    """Die Belege-Seite; mit `document_kind` (Schlüssel einer angemeldeten Dokumentart) und `year`
    ist das Aufnehmen-Formular so vorbelegt, und die Seite zeigt dieses Jahr. `query` (Suche) und
    `types` (Werte der Dateitypen) sind Suche und Filter der Seite."""
    pairs = [
        (name, value)
        for name, value in (("dokumentart", document_kind), ("jahr", year), ("datei", file))
        if value is not None
    ]
    pairs.extend(_filter_pairs(query, types))
    return f"/belege?{urlencode(pairs)}" if pairs else "/belege"


def site_file_url(sha256: str) -> str:
    """Eine Datei eines Ablageorts (Vorschau), erkannt am SHA-256."""
    return f"/belege/datei/{sha256}"


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: die Belege-Seite, das Dokument gewählt."""
    return f"/belege?dokument={document_id}"


def document_file_url(document_id: str) -> str:
    """Die Datei eines Dokuments (Vorschau)."""
    return f"/dokumente/{document_id}/datei"


def expected_documents_url(expected_id: str | None = None) -> str:
    """Der Abschnitt Erwartete Belege der Belege-Seite; mit `expected_id` die Seite, auf der man
    den Erwarteten Beleg ändert."""
    return "/belege#erwartet" if expected_id is None else f"/belege/erwartet/{expected_id}"


def issuers_url() -> str:
    return "/aussteller"


def issuer_url(issuer_id: str) -> str:
    return f"/aussteller/{issuer_id}"


def mein_elster_url() -> str:
    """Die Anmeldung bei Mein ELSTER: der einzige Link nach außen, nur ein Klick öffnet ihn
    (PRINCIPLES.md 8)."""
    return "https://www.elster.de/eportal/login/softpse"
