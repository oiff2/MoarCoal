"""Adressen der Seiten zu den Bausteinen der Datenebene (die Datenebene kennt keine Routen).

Wer außerhalb einer Routen-Angabe eine Adresse braucht (Befund, Seitenleiste, Vorschau), baut sie
hier; der Testkern weist Routen in `storage/` und `values/` ab.

Der Import von `storage.issuers.portal_problem` ist gewollt: ein vom Nutzer eingegebenes Portal
wird nur hier zum Link nach außen, und zwar nach derselben Regel, mit der der Vorgang das Portal
prüft (PRINCIPLES.md 8).
"""

from collections.abc import Iterable
from urllib.parse import urlencode, urlsplit

from moarcoal.document_filter import SearchFilter
from moarcoal.storage.issuers import portal_problem


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
    document: str | None = None,
) -> str:
    """Die Belege-Seite; mit `document_kind` (Schlüssel einer angemeldeten Dokumentart) und `year`
    ist das Aufnehmen-Formular so vorbelegt, und die Seite zeigt dieses Jahr. `query` (Suche) und
    `types` (Werte der Dateitypen) sind Suche und Filter der Seite; `file` (SHA-256) wählt eine
    Datei, `document` (Kennung) ein Dokument."""
    pairs = [
        (name, value)
        for name, value in (
            ("dokument", document),
            ("datei", file),
            ("dokumentart", document_kind),
            ("jahr", year),
        )
        if value is not None
    ]
    pairs.extend(_filter_pairs(query, types))
    return f"/belege?{urlencode(pairs)}" if pairs else "/belege"


def site_return_url(text: str) -> str | None:
    """`text` als Rücksprung auf die Belege-Seite, sonst `None`: nur der Pfad `/belege` mit
    beliebiger Abfrage zählt, nie eine fremde oder absolute Adresse."""
    parts = urlsplit(text)
    if text != text.strip() or "\\" in text or parts.scheme or parts.netloc:
        return None
    if parts.path != "/belege" or parts.fragment:
        return None
    return f"/belege?{parts.query}" if parts.query else "/belege"


def site_file_url(sha256: str) -> str:
    """Eine Datei eines Ablageorts (Vorschau), erkannt am SHA-256."""
    return f"/belege/datei/{sha256}"


def document_url(document_id: str) -> str:
    """Die Adresse eines Dokuments: die Belege-Seite, das Dokument gewählt."""
    return site_url(document=document_id)


def document_file_url(document_id: str) -> str:
    """Die Datei eines Dokuments (Vorschau)."""
    return f"/dokumente/{document_id}/datei"


def expected_documents_url(expected_id: str | None = None) -> str:
    """Der Abschnitt Erwartete Belege der Belege-Seite; mit `expected_id` die Seite, auf der man
    den Erwarteten Beleg ändert."""
    return "/belege#erwartet" if expected_id is None else f"/belege/erwartet/{expected_id}"


def findings_url(year: int, *, hidden: bool = False) -> str:
    """Die Befunde-Seite eines Jahrs; mit `hidden` zeigt sie auch die ausgeblendeten Befunde."""
    return f"/befunde?{urlencode([('year', year), *([('ausgeblendet', 1)] if hidden else [])])}"


def issuers_url(query: str = "", filter_value: str = "") -> str:
    """Die Aussteller-Liste; Suche und Filter stehen in der Adresse (nur gesetzte)."""
    params = [(k, v) for k, v in (("q", query), ("filter", filter_value)) if v]
    return f"/aussteller?{urlencode(params)}" if params else "/aussteller"


def issuer_url(issuer_id: str, query: str = "", filter_value: str = "") -> str:
    """Die Aussteller-Seite mit diesem Aussteller gewählt (dorthin schickt auch Speichern seiner
    Angaben); Suche und Filter der Liste bleiben (nur gesetzte)."""
    params = [(k, v) for k, v in (("q", query), ("filter", filter_value)) if v]
    return f"/aussteller/{issuer_id}" + (f"?{urlencode(params)}" if params else "")


def issuer_delete_url(issuer_id: str) -> str:
    """Löschen eines Ausstellers (POST)."""
    return f"/aussteller/{issuer_id}/loeschen"


def issuer_merge_url(issuer_id: str) -> str:
    """Zusammenführen eines Ausstellers: GET zeigt die Folgenseite, POST führt zusammen."""
    return f"/aussteller/{issuer_id}/zusammenfuehren"


def mein_elster_url() -> str:
    """Die Anmeldung bei Mein ELSTER: der einzige Link nach außen, nur ein Klick öffnet ihn
    (PRINCIPLES.md 8)."""
    return "https://www.elster.de/eportal/login/softpse"


def portal_link(portal: str | None) -> str | None:
    """Das Portal eines Ausstellers als Link nach außen, nur wenn es eine http(s)-Adresse ist; nur
    ein Klick öffnet ihn (PRINCIPLES.md 8)."""
    return portal if portal and portal_problem(portal) is None else None


def agreements_url() -> str:
    return "/vertraege"


def agreement_url(agreement_id: str) -> str:
    return f"/vertraege/{agreement_id}"
