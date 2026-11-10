"""PROTOTYP – wegwerfen. Skizze der Python-Schnittstelle der Datenebene.

Ticket: „Python-Schnittstelle der Datenebene als Skizze“ (oiff2/MoarCoal#19).
Nur Signaturen und Typen mit gerade so viel Rumpf, dass demo.py läuft.
Bewusst vereinfacht: dataclasses statt Pydantic, Speicher im Arbeitsspeicher
statt JSON, keine Fehlerbehandlung, keine Tests.

Englische Namen sind Vorschläge; sie kommen erst nach Bestätigung als
`(Code: …)` in CONTEXT.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum, IntEnum
from typing import NewType, Protocol

# ---------------------------------------------------------------------------
# Grundtypen
# ---------------------------------------------------------------------------

UserId = NewType("UserId", str)  # Nutzer
ModuleKey = NewType("ModuleKey", str)  # z. B. "property"
ValueKey = NewType("ValueKey", str)  # Schlüssel im Wertekatalog, Präfix = ModuleKey


class Unit(Enum):
    EUR = "€"
    DAYS = "Tage"
    KM = "km"
    SQM = "m²"
    PERCENT = "%"


@dataclass(frozen=True, order=True)
class Money:
    """Geldbetrag in ganzen Cent, nur EUR."""

    cents: int

    unit = Unit.EUR

    def __add__(self, other: Money) -> Money:
        return Money(self.cents + other.cents)

    def __str__(self) -> str:
        euros, cents = divmod(abs(self.cents), 100)
        sign = "-" if self.cents < 0 else ""
        return f"{sign}{euros:,}".replace(",", ".") + f",{cents:02d} €"

    @staticmethod
    def eur(text: str) -> Money:
        return Money(int(Decimal(text) * 100))


@dataclass(frozen=True)
class Quantity:
    """Nicht-Geld-Einheit (Tage, km, m², %)."""

    value: Decimal
    unit: Unit

    def __str__(self) -> str:
        return f"{self.value} {self.unit.value}"


type Amount = Money | Quantity


def unit_of(amount: Amount) -> Unit:
    return Unit.EUR if isinstance(amount, Money) else amount.unit


@dataclass(frozen=True)
class Period:
    """Zeitraum: Intervall von Tagen, meist ein Kalenderjahr."""

    start: date
    end: date

    @staticmethod
    def year(y: int) -> Period:
        return Period(date(y, 1, 1), date(y, 12, 31))

    def __str__(self) -> str:
        if (self.start.month, self.start.day, self.end.month, self.end.day) == (1, 1, 12, 31):
            return str(self.start.year)
        return f"{self.start}–{self.end}"


@dataclass(frozen=True)
class KeyDate:
    """Stichtag eines Stichtagswerts."""

    day: date

    def __str__(self) -> str:
        return f"Stichtag {self.day}"


type TimeRef = Period | KeyDate


@dataclass(frozen=True)
class Subject:
    """Bezugsobjekt. Aufbau der id ist offen („Kennungen und Verweise“, #20)."""

    id: str
    display_name: str


class Backing(IntEnum):
    """Belegstand. Ordnung = Stärke; min() ergibt den schwächsten.

    Entschieden (#19): ausstehend < angenommen < belegt.
    """

    PENDING = 0  # ausstehend
    ASSUMED = 1  # angenommen
    BACKED = 2  # belegt

    def __str__(self) -> str:
        return {0: "ausstehend", 1: "angenommen", 2: "belegt"}[self.value]


class Source(Enum):
    """Quelle: der Kanal von außen."""

    EDATA = "eDaten-Abruf"
    EXTRACTION = "Dokumentauslesung"
    TRANSMISSION_PROTOCOL = "Übertragungsprotokoll"
    USER_INPUT = "Nutzereingabe"


# ---------------------------------------------------------------------------
# Fundstelle (Locator) – die Quelle ergibt sich daraus
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentLocator:
    """Stelle in einem Beleg.

    Entschieden (#19): Die Fundstelle führt die Quelle mit, denn dasselbe
    Dokument kann ausgelesen (Claude) oder eingelesen (exakt) sein.
    """

    document_id: str
    source: Source
    page: int | None = None
    line: int | None = None

    def __str__(self) -> str:
        where = "".join(
            [f", S. {self.page}" if self.page else "", f", Z. {self.line}" if self.line else ""]
        )
        return f"Dokument {self.document_id}{where}"


@dataclass(frozen=True)
class EDataLocator:
    record_id: str
    source = Source.EDATA

    def __str__(self) -> str:
        return f"eDaten-Satz {self.record_id}"


@dataclass(frozen=True)
class UserInputLocator:
    entered_on: date
    source = Source.USER_INPUT

    def __str__(self) -> str:
        return f"Nutzereingabe vom {self.entered_on}"


@dataclass(frozen=True)
class ValueLocator:
    """Fundstelle = anderer Ausgewiesener Wert (Kette).

    Entschieden (#19): Ein Verweis-Posten hat keine eigene Quelle (None);
    die Oberfläche zeigt stattdessen den fremden Wert zum Aufklappen.
    """

    request: ValueRequest
    source = None

    def __str__(self) -> str:
        r = self.request
        return f"Ausgewiesener Wert {r.key} ({r.time}{', ' + r.subject_id if r.subject_id else ''})"


type Locator = DocumentLocator | EDataLocator | UserInputLocator | ValueLocator


@dataclass(frozen=True)
class LineItem:
    """Einzelposten: eine Eingabe in die Rechnung, mit Einheit, Fundstelle, Belegstand."""

    label: str
    amount: Amount
    locator: Locator
    backing: Backing
    via: ExposedValue | None = None  # nur bei ValueLocator: der fremde Wert zum Aufklappen

    @property
    def source(self) -> Source | None:
        return self.locator.source


# ---------------------------------------------------------------------------
# Rechenweg (Workings)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    kind: str  # "Eingang" | "Zwischenergebnis" | "Entscheidung"
    text: str
    amount: Amount | None = None


# ---------------------------------------------------------------------------
# Anfrage und Ergebnis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueRequest:
    key: ValueKey
    user: UserId
    time: TimeRef
    subject_id: str | None = None  # None = Wert ohne Bezugsobjekt


@dataclass(frozen=True)
class ExposedValue:
    """Ausgewiesener Wert: Ergebnis einer Rechnung, mit Einzelposten und Rechenweg."""

    key: ValueKey
    user: UserId
    time: TimeRef
    subject: Subject | None
    amount: Amount
    items: tuple[LineItem, ...]
    workings: tuple[Step, ...]

    @property
    def backing(self) -> Backing:
        """Schwächster Belegstand; ohne Einzelposten belegt (entschieden in #19)."""
        return min((i.backing for i in self.items), default=Backing.BACKED)


@dataclass(frozen=True)
class NotYetComputable:
    """„noch nicht berechenbar“ – mit Grund und der Ursache weiter unten in der Kette."""

    request: ValueRequest
    reason: str
    cause: NotYetComputable | None = None

    def chain(self) -> Iterator[NotYetComputable]:
        n: NotYetComputable | None = self
        while n:
            yield n
            n = n.cause


type Outcome = ExposedValue | NotYetComputable


# ---------------------------------------------------------------------------
# Befund (nur so weit, wie die Datenebene ihn beim Rechnen erzeugt)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    severity: str  # Hinweis | Warnung | Fehler
    kind: str
    text: str
    target: str  # LÜCKE: Adresse des betroffenen Eintrags (#20)


# ---------------------------------------------------------------------------
# Modulanmeldung und Wertekatalog
# ---------------------------------------------------------------------------


type ComputeFn[D] = Callable[[Calculation[D]], Amount]
type SubjectsFn[D] = Callable[[D, TimeRef], Sequence[Subject]]


@dataclass(frozen=True)
class CatalogEntry:
    """Eintrag im Wertekatalog: was ein Schlüssel bedeutet."""

    key: ValueKey
    meaning: str
    unit: Unit
    time_kind: type[Period] | type[KeyDate]
    needs_subject: bool


@dataclass(frozen=True)
class ValueDefinition[D]:
    """Was ein Modul je Schlüssel anmeldet: Katalogeintrag + Rechnung + Aufzählung."""

    entry: CatalogEntry
    compute: ComputeFn[D]
    subjects: SubjectsFn[D] | None = None  # Pflicht, wenn needs_subject


@dataclass(frozen=True)
class ModuleRegistration[D]:
    """Modulanmeldung (Ausschnitt; Seiten, Auslese-Vorlagen, Befunde weggelassen)."""

    key: ModuleKey
    display_name: str
    empty_data: Callable[[], D]  # Datenmodell; Laden macht die Datenebene
    values: Sequence[ValueDefinition[D]]


class ValueCatalog:
    """Wertekatalog: alle Schlüssel aller angemeldeten Module."""

    def __init__(self, registrations: Sequence[ModuleRegistration[object]]) -> None:
        self._by_key: dict[ValueKey, tuple[ModuleRegistration[object], ValueDefinition[object]]] = {}
        for reg in registrations:
            for d in reg.values:
                assert d.entry.key.startswith(reg.key + "."), "Schlüssel-Präfix = Modul"
                assert d.entry.key not in self._by_key, "Schlüssel doppelt"
                assert not d.entry.needs_subject or d.subjects, "Aufzählung fehlt"
                self._by_key[d.entry.key] = (reg, d)

    def lookup(self, key: ValueKey) -> tuple[ModuleRegistration[object], ValueDefinition[object]]:
        if key not in self._by_key:
            raise KeyError(f"Unbekannter Schlüssel {key}")  # Fehler, nie stille Null
        return self._by_key[key]

    def entries(self) -> list[CatalogEntry]:
        return [d.entry for _, d in self._by_key.values()]


# ---------------------------------------------------------------------------
# Speicherzugang
# ---------------------------------------------------------------------------


class Store(Protocol):
    """Einziger Weg zu Dateien. Echte Fassung: JSON unter ~/MoarCoal/nutzer/<id>/<modul>/,
    Schreibweg siehe „Schreibweg der Datenebene“ (#22)."""

    def read[D](self, user: UserId, module: ModuleKey, empty: Callable[[], D]) -> D: ...
    def write(self, user: UserId, module: ModuleKey, data: object) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[tuple[UserId, ModuleKey], object] = {}

    def read[D](self, user: UserId, module: ModuleKey, empty: Callable[[], D]) -> D:
        return self._data.get((user, module), empty())  # type: ignore[return-value]

    def write(self, user: UserId, module: ModuleKey, data: object) -> None:
        self._data[(user, module)] = data


# ---------------------------------------------------------------------------
# Rechenkontext: was ein Modul beim Rechnen in die Hand bekommt
# ---------------------------------------------------------------------------


class _Missing(Exception):
    def __init__(self, ncy: NotYetComputable) -> None:
        self.ncy = ncy


class Calculation[D]:
    """Eine laufende Rechnung für genau eine ValueRequest.

    Das Modul sieht: seine eigenen Daten (schon geladen, nur lesen), das
    Bezugsobjekt, den Zeitbezug, und Werkzeuge für Einzelposten, Ketten und
    Rechenweg. Es sieht keinen Store und keine anderen Module.
    """

    def __init__(self, values: Values, request: ValueRequest, subject: Subject | None, data: D) -> None:
        self._values = values
        self.request = request
        self.subject = subject
        self.data = data
        self.items: list[LineItem] = []
        self.workings: list[Step] = []

    @property
    def time(self) -> TimeRef:
        return self.request.time

    @property
    def year(self) -> int:
        assert isinstance(self.time, Period)
        return self.time.start.year

    # --- Einzelposten -----------------------------------------------------

    def item(self, label: str, amount: Amount, locator: Locator, backing: Backing) -> LineItem:
        li = LineItem(label, amount, locator, backing)
        self.items.append(li)
        self.workings.append(Step("Eingang", label, amount))
        return li

    # --- Ketten -----------------------------------------------------------

    def try_use(
        self, key: ValueKey, *, subject_id: str | None = None, time: TimeRef | None = None, label: str | None = None
    ) -> LineItem | NotYetComputable:
        """Fremden Wert als Verweis-Posten holen; Fehlen ausdrücklich behandeln."""
        req = ValueRequest(key, self.request.user, time or self.time, subject_id)
        out = self._values.get_one(req)
        if isinstance(out, NotYetComputable):
            return out
        li = LineItem(
            label or f"{key}{' / ' + out.subject.display_name if out.subject else ''}",
            out.amount,
            ValueLocator(req),
            out.backing,
            via=out,
        )
        self.items.append(li)
        self.workings.append(Step("Eingang", li.label, li.amount))
        return li

    def use(self, key: ValueKey, **kw: object) -> LineItem:
        """Wie try_use, aber Fehlen macht diese Rechnung auch „noch nicht berechenbar“."""
        out = self.try_use(key, **kw)  # type: ignore[arg-type]
        if isinstance(out, NotYetComputable):
            raise _Missing(out)
        return out

    def subjects_of(self, key: ValueKey, time: TimeRef | None = None) -> list[Subject]:
        """Bezugsobjekte eines fremden Schlüssels; aufgezählt vom Modul, dem er gehört."""
        return self._values.subjects(key, self.request.user, time or self.time)

    # --- Rechenweg ----------------------------------------------------------

    def step(self, text: str, amount: Amount) -> Amount:
        self.workings.append(Step("Zwischenergebnis", text, amount))
        return amount

    def decide(self, text: str) -> None:
        self.workings.append(Step("Entscheidung", text))

    def not_yet(self, reason: str) -> None:
        """Ausdrücklich: diese Rechnung kann (noch) nicht rechnen."""
        raise _Missing(NotYetComputable(self.request, reason))


# ---------------------------------------------------------------------------
# Values: Einstieg für Verbraucher; eine Instanz je Anfrage (HTTP-Request)
# ---------------------------------------------------------------------------


class Values:
    """Berechnet Ausgewiesene Werte auf Anfrage.

    Zwischenspeicher gilt nur für diese Instanz, also eine Seite/Befundliste.
    Zyklen werden über den Stapel der laufenden Anfragen erkannt.
    """

    def __init__(
        self, catalog: ValueCatalog, store: Store, *, disabled: frozenset[tuple[UserId, ModuleKey]] = frozenset()
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._disabled = disabled
        self._cache: dict[ValueRequest, Outcome] = {}
        self._data: dict[tuple[UserId, ModuleKey], object] = {}
        self._stack: list[ValueRequest] = []
        self.findings: list[Finding] = []

    # --- für Verbraucher ----------------------------------------------------

    def get(self, key: ValueKey, user: UserId, time: TimeRef) -> dict[Subject | None, Outcome]:
        """Ein Ergebnis je Bezugsobjekt (oder {None: …} ohne Bezugsobjekt)."""
        _, d = self._catalog.lookup(key)
        if not d.entry.needs_subject:
            return {None: self.get_one(ValueRequest(key, user, time))}
        return {s: self.get_one(ValueRequest(key, user, time, s.id)) for s in self.subjects(key, user, time)}

    def subjects(self, key: ValueKey, user: UserId, time: TimeRef) -> list[Subject]:
        reg, d = self._catalog.lookup(key)
        assert d.subjects
        return list(d.subjects(self._load(user, reg), time))

    def get_one(self, req: ValueRequest) -> Outcome:
        if req in self._cache:
            return self._cache[req]
        if req in self._stack:
            loop = self._stack[self._stack.index(req) :] + [req]
            text = " → ".join(r.key for r in loop)
            self.findings.append(Finding("Fehler", "Zyklus", text, req.key))
            return NotYetComputable(req, f"Zyklus: {text}")
        self._stack.append(req)
        try:
            out = self._compute(req)
        finally:
            self._stack.pop()
        self._cache[req] = out
        if isinstance(out, NotYetComputable) and out.cause is None:
            self.findings.append(Finding("Fehler", "noch nicht berechenbar", out.reason, req.key))
        if isinstance(out, ExposedValue):
            self._check_duplicate_locators(out)
        return out

    # --- intern -------------------------------------------------------------

    def _load(self, user: UserId, reg: ModuleRegistration[object]) -> object:
        k = (user, reg.key)
        if k not in self._data:
            self._data[k] = self._store.read(user, reg.key, reg.empty_data)
        return self._data[k]

    def _compute(self, req: ValueRequest) -> Outcome:
        reg, d = self._catalog.lookup(req.key)
        e = d.entry
        assert isinstance(req.time, e.time_kind), f"{req.key} erwartet {e.time_kind.__name__}"
        assert (req.subject_id is not None) == e.needs_subject, f"{req.key}: Bezugsobjekt passt nicht"
        if (req.user, reg.key) in self._disabled:
            # LÜCKE: Regel offen („Abgeschaltetes Modul und ‚noch nicht berechenbar‘“, #24)
            return NotYetComputable(req, f"Modul {reg.display_name} ist abgeschaltet")
        data = self._load(req.user, reg)
        subject = None
        if req.subject_id is not None:
            subject = next((s for s in self.subjects(req.key, req.user, req.time) if s.id == req.subject_id), None)
            if subject is None:
                return NotYetComputable(req, f"Bezugsobjekt {req.subject_id} unbekannt")
        calc = Calculation(self, req, subject, data)
        try:
            amount = d.compute(calc)
        except _Missing as m:
            if m.ncy.request == req:
                return m.ncy
            return NotYetComputable(req, f"stützt sich auf {m.ncy.request.key}", cause=m.ncy)
        assert unit_of(amount) == e.unit, f"{req.key}: Einheit {unit_of(amount)} statt {e.unit}"
        return ExposedValue(req.key, req.user, req.time, subject, amount, tuple(calc.items), tuple(calc.workings))

    def _check_duplicate_locators(self, v: ExposedValue) -> None:
        """Gleiche Fundstelle zweimal im selben Wert, auch über Ketten (#18)."""
        seen: set[Locator] = set()
        for li in walk_items(v):
            if isinstance(li.locator, ValueLocator):
                continue
            if li.locator in seen:
                self.findings.append(
                    Finding("Fehler", "doppelte Fundstelle", f"{li.locator} doppelt in {v.key}", v.key)
                )
            seen.add(li.locator)


def walk_items(v: ExposedValue) -> Iterator[LineItem]:
    for li in v.items:
        yield li
        if li.via:
            yield from walk_items(li.via)


# ---------------------------------------------------------------------------
# Schnappschuss (nur Signatur und Rohform)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    user: UserId
    occasion: str
    frozen_on: date
    trigger_document_id: str | None
    values: tuple[Outcome, ...]  # ganze Kette steckt in LineItem.via; auch noch nicht berechenbare
    copied_documents: tuple[str, ...] = field(default=())


def freeze(values: Values, requests: Sequence[ValueRequest], occasion: str, trigger_document_id: str | None) -> Snapshot:
    """Einfrieren hält fest, was abgegeben wurde; es verhindert nichts.

    Entschieden (#19): Noch nicht berechenbare Werte werden mit Grund mit
    eingefroren, dazu ein Befund (Fehler).
    """
    outs = [values.get_one(r) for r in requests]
    for o in outs:
        if isinstance(o, NotYetComputable):
            values.findings.append(
                Finding("Fehler", "eingefroren, aber noch nicht berechenbar", f"{o.request.key}: {o.reason}", o.request.key)
            )
    evs = [o for o in outs if isinstance(o, ExposedValue)]
    docs = sorted(
        {li.locator.document_id for v in evs for li in walk_items(v) if isinstance(li.locator, DocumentLocator)}
        | ({trigger_document_id} if trigger_document_id else set())
    )
    return Snapshot(requests[0].user, occasion, date.today(), trigger_document_id, tuple(outs), tuple(docs))
