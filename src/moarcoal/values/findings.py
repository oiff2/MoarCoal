"""Befunde und Befundarten; die Datenebene erzeugt beim Rechnen den Zyklus, Module den Rest."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from moarcoal.storage import Dismissal, EntryAddress
from moarcoal.values.model import KeyDate, Period, ValueRef


class Severity(StrEnum):
    """Schweregrad eines Befunds; der Wert ist die Anzeige."""

    NOTE = "Hinweis"
    WARNING = "Warnung"
    ERROR = "Fehler"


@dataclass(frozen=True)
class FindingKind:
    """Eine Befundart, die ein Modul anmeldet: Schlüssel (`<modul>.<name>`) und Titel."""

    key: str
    title: str


def fingerprint(*parts: object) -> str:
    """Fingerabdruck eines Stands aus den Teilen, die der Erzeuger wählt (SHA-256 als Text)."""
    canonical = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def target_text(target: ValueRef | EntryAddress | str) -> str:
    """Das Ziel als Text, mit dem ein Befund erkannt wird (ohne Nutzer)."""
    if isinstance(target, str):
        return target
    if isinstance(target, EntryAddress):
        return str(target)
    match target.time:
        case Period(start=start, end=end):
            time = f"{start}..{end}"
        case KeyDate(day=day):
            time = f"{day}"
    subject = "" if target.subject is None else f"/{target.subject.address}"
    return f"{target.key}@{time}{subject}"


@dataclass(frozen=True)
class Finding:
    """Ein Befund: Befundart (`kind`), Schweregrad, Ziel, Text und ggf. Kette.

    `href` führt zur Stelle, an der man den Befund prüft (leer: kein Link). `fingerprint` ist der
    Fingerabdruck des Stands, aus dem der Erzeuger den Befund gebildet hat (`fingerprint(...)`);
    ohne Angabe ist es der des Texts. Ein Ziel als Text steht für etwas ohne Adresse (z. B. den
    Eingang). Erkannt wird ein Befund an Befundart und Ziel.
    """

    kind: str
    severity: Severity
    target: ValueRef | EntryAddress | str
    message: str
    chain: tuple[ValueRef, ...] = ()
    href: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", fingerprint(self.message))

    @property
    def identity(self) -> tuple[str, str]:
        return (self.kind, target_text(self.target))


CYCLE = "cycle"
DUPLICATE_LOCATOR = "duplicate_locator"
INCOMING_FILES = "incoming_files"
DENYLIST_NOT_WRITTEN = "denylist_not_written"


@dataclass(frozen=True)
class HiddenFinding:
    """Ein ausgeblendeter Befund mit der Ausblendung, die ihn verbirgt."""

    finding: Finding
    dismissal: Dismissal


@dataclass(frozen=True)
class FindingList:
    """Die Befundliste eines Nutzers: sichtbare Befunde, ausgeblendete und frühere Ausblendungen.

    `earlier` nennt zu einem sichtbaren Befund die jüngste Ausblendung, die für ihn einmal galt
    und wegen eines anderen Fingerabdrucks nicht mehr gilt (der Befund ist zurückgekehrt).
    """

    visible: list[Finding]
    hidden: list[HiddenFinding]
    earlier: dict[tuple[str, str], Dismissal]

    @property
    def hidden_errors(self) -> int:
        return sum(1 for h in self.hidden if h.finding.severity is Severity.ERROR)

    def hidden_count(self, severity: Severity | None = None) -> int:
        return sum(1 for h in self.hidden if severity in (None, h.finding.severity))


def split_findings(found: list[Finding], dismissals: list[Dismissal]) -> FindingList:
    """Teilt Befunde nach den Ausblendungen des Nutzers; Reihenfolge bleibt erhalten."""
    by_identity: dict[tuple[str, str], list[Dismissal]] = {}
    for dismissal in dismissals:
        by_identity.setdefault((dismissal.finding_kind, dismissal.target), []).append(dismissal)
    visible: list[Finding] = []
    hidden: list[HiddenFinding] = []
    earlier: dict[tuple[str, str], Dismissal] = {}
    for finding in found:
        candidates = by_identity.get(finding.identity, [])
        current = next((d for d in candidates if d.fingerprint == finding.fingerprint), None)
        if current is not None:
            hidden.append(HiddenFinding(finding, current))
            continue
        visible.append(finding)
        if candidates:
            earlier[finding.identity] = max(candidates, key=lambda d: (d.noted_on, d.id))
    return FindingList(visible, hidden, earlier)
