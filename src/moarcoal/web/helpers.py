"""Gemeinsame Helfer der Seiten: Vorlagen, Nutzer, Stand und Formularfelder."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from typing import Any, Protocol
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from moarcoal.defaults import DEFAULT_YEAR, year_of
from moarcoal.documents import DocumentKind, read_entries_of
from moarcoal.incoming import all_site_files, incoming_files
from moarcoal.personal_details import details_of
from moarcoal.registration import ModuleRegistration, ModuleState
from moarcoal.storage import (
    Document,
    Entry,
    EntryAddress,
    ExpectedDocument,
    Issuer,
    Proposal,
    Rejected,
    Rereading,
    State,
    Store,
)
from moarcoal.values.engine import Values
from moarcoal.values.findings import INCOMING_TARGET, Finding, FindingList, HiddenFinding, Severity
from moarcoal.values.model import ValueRef
from moarcoal.web.links import (
    document_url,
    expected_documents_url,
    issuer_url,
    issuers_url,
    site_url,
)

MAX_YEARS = 10  # so viele Jahre mit Daten stehen höchstens zur Auswahl
YEAR_COOKIE = "jahr"  # das globale Jahr merkt sich der Browser, kein Eintrag der Datenebene


def year_choices(found: Iterable[int], chosen: int) -> list[int]:
    """Jahre zur Auswahl, neueste zuerst: die neuesten `MAX_YEARS` aus `found` und `DEFAULT_YEAR`;
    das gewählte Jahr steht zusätzlich an seinem Platz."""
    years = set(sorted({DEFAULT_YEAR, *found}, reverse=True)[:MAX_YEARS])
    return sorted(years | {chosen}, reverse=True)


def global_year(request: Request) -> int:
    """Das globale Jahr aus der Kopfleiste, ohne Wahl `DEFAULT_YEAR`; Seiten dürfen es
    übersteuern."""
    year = year_of(request.cookies.get(YEAR_COOKIE, ""), in_range=True)
    return DEFAULT_YEAR if year is None else year


@dataclass(frozen=True)
class NavEntry:
    """Ein Eintrag der Seitenleiste: Name, Adresse, Icon (Datei in `templates/icons/`), Zähler."""

    label: str
    url: str
    icon: str
    count: int = 0


@dataclass(frozen=True)
class FindingsSummary:
    """Befundübersicht der Kopfleiste: die sichtbaren Befunde eines Jahrs je Schweregrad."""

    year: int
    counts: dict[Severity, int]
    top: Finding | None


def entry_url(modules: tuple[ModuleRegistration, ...], address: EntryAddress) -> str | None:
    """Link zum Eintrag, wie das besitzende Modul ihn nennt; unbekannte Art: kein Link."""
    if address.kind == Document.__name__:  # Baustein der Datenebene
        return document_url(address.id)
    if address.kind == ExpectedDocument.__name__:  # Baustein der Datenebene
        return expected_documents_url(address.id)
    if address.kind == Issuer.__name__:  # Baustein der Datenebene
        return issuer_url(address.id)
    return next((url for m in modules if (url := m.entry_url(address)) is not None), None)


def capture_links(
    modules: Sequence[ModuleRegistration], state: State, user: str, refs: Iterable[ValueRef]
) -> list[tuple[str, str]]:
    """Je Wert die Erfassungsstelle des Moduls, dem sein Schlüssel gehört (Beschriftung,
    Adresse); gleiche Adressen einmal, Werte ohne Erfassungsstelle fallen weg."""
    owners = {d.entry.key: m for m in modules for d in m.values}
    links: list[tuple[str, str]] = []
    for ref in refs:
        owner = owners.get(ref.key)
        link = (
            None
            if owner is None
            else owner.capture_url(ref.key, ref.time, ref.subject, ModuleState(state, owner, user))
        )
        if link is not None and all(url != link[1] for _, url in links):
            links.append(link)
    return links


def finding_url(
    modules: tuple[ModuleRegistration, ...], state: State, finding: Finding
) -> str | None:
    """Link eines Befunds: ein gesetztes `href` geht vor, sonst baut ihn die Anbindung aus dem Ziel.

    Eine Adresse löst `entry_url` auf; ein Vorschlag führt zur Seite seines Dokuments, eine
    Neueinlesung zum ersten eingelesenen Eintrag ihres Dokuments. Text-Ziele: der Eingang zur
    Belege-Seite, `<Adresse>@<Jahr>` eines Erwarteten Belegs zu deren Abschnitt Erwartete Belege.
    """
    if finding.href:
        return finding.href
    target = finding.target
    if isinstance(target, EntryAddress):
        entry = state.get(target)
        if isinstance(entry, Proposal):
            return entry_url(modules, entry.document)
        if isinstance(entry, Rereading):
            entries = read_entries_of(state, entry.document)
            return next((url for e in entries if (url := entry_url(modules, e.address))), None)
        return entry_url(modules, target)
    if not isinstance(target, str):  # ein Wert: der Befund hat keinen eigenen Link
        return None
    if target == INCOMING_TARGET:
        return site_url()
    address, _, year = target.partition("@")
    if year.isdigit() and address.startswith(f"{ExpectedDocument.__name__}:"):
        return expected_documents_url()
    return None


def linked_findings(
    modules: tuple[ModuleRegistration, ...], state: State, found: FindingList
) -> FindingList:
    """`found` mit dem Link jedes Befunds in `href`; die Vorlagen lesen ihn dort."""

    def linked(finding: Finding) -> Finding:
        return replace(finding, href=finding_url(modules, state, finding) or "")

    return FindingList(
        [linked(f) for f in found.visible],
        [HiddenFinding(linked(h.finding), h.dismissal) for h in found.hidden],
        found.earlier,
    )


def finding_list_of(request: Request, year: int) -> FindingList:
    """Die Befundliste des Nutzers im Jahr, jeder Befund mit seinem Link."""
    state = store_of(request).state()
    found = values_on(request, state).finding_list(user_of(request), year)
    return linked_findings(request.app.state.modules, state, found)


def values_on(request: Request, state: State) -> Values:
    """`Values` der Anwendung auf einem beliebigen Stand (z. B. einem vorläufigen)."""
    store = store_of(request)
    return Values(
        request.app.state.modules,
        state,
        site_files=lambda: all_site_files(store),
        sites=store.sites,
        entry_kinds=store.entry_kinds,
    )


def values_of(request: Request) -> Values:
    """`Values` der Anfrage, auf dem Stand zu Beginn der Anfrage."""
    return values_on(request, store_of(request).state())


def document_kinds(request: Request) -> dict[str, DocumentKind]:
    """Alle Dokumentarten aller Modulanmeldungen, nach Schlüssel."""
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    return {k.key: k for r in registrations for k in r.document_kinds}


def store_of(request: Request) -> Store:
    return request.app.state.store


def user_of(request: Request) -> str:
    return request.app.state.user


def user_name_of(request: Request) -> str | None:
    """Der Name des Nutzers aus seinen Angaben zur Person; `None`, solange es den Nutzer nicht
    gibt."""
    details = details_of(store_of(request).state(), user_of(request))
    return None if details is None else details.display_name


PAGES_WITHOUT_USER = frozenset({"/", "/person"})  # und /static (eigene Anwendung, keine Route)


def require_user(request: Request) -> None:
    """Ohne Nutzer (ohne Angaben zur Person) führt jede Seite außer der Startseite und den Angaben
    zur Person mit 303 auf die Startseite."""
    if request.url.path in PAGES_WITHOUT_USER:
        return  # diese Seiten können den Nutzer anlegen; `render` ermittelt den Namen dann selbst
    user_name = user_name_of(request)
    if user_name is None:
        raise HTTPException(303, headers={"Location": "/"})
    request.state.user_name = user_name  # `render` liest ihn hier, statt ihn neu zu ermitteln


def module_state(request: Request, key: str) -> ModuleState:
    """Der Stand der Anfrage, eingegrenzt auf das Modul `key` und den Nutzer."""
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    registration = next(r for r in registrations if r.key == key)
    return ModuleState(store_of(request).state(), registration, user_of(request))


async def form_fields(request: Request) -> dict[str, str]:
    """Felder eines Formulars (application/x-www-form-urlencoded), je Feld der erste Wert."""
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = parse_qs(body, keep_blank_values=True)
    return {name: values[0] for name, values in parsed.items()}


class _Lookup(Protocol):
    def get(self, address: EntryAddress) -> Entry | None: ...


def entry_of[E: Entry](state: _Lookup, kind: type[E], entry_id: str, owner: str | None = None) -> E:
    """Der Eintrag der Art `kind` mit dieser Kennung, sonst 404: ungültige Kennung, es gibt ihn
    nicht, oder er gehört einem anderen als `owner` (`None`: Eigentümer egal, z. B. bei
    gemeinsamen Einträgen oder einem Stand, der schon auf den Nutzer eingegrenzt ist)."""
    try:
        address = EntryAddress(kind=kind.__name__, id=entry_id)
    except ValueError as error:
        raise HTTPException(404) from error
    entry = state.get(address)
    if not isinstance(entry, kind) or (owner is not None and entry.owner != owner):
        raise HTTPException(404)
    return entry


def rejection_reasons(result: Rejected) -> list[str]:
    """Die Gründe eines abgewiesenen Vorgangs als Liste, für die Fehlerliste einer Seite."""
    return list(result.reasons.values())


def rejection_text(result: Rejected) -> str:
    """Die Gründe eines abgewiesenen Vorgangs als ein Text, für einen Hinweis auf der Seite."""
    return " ".join(rejection_reasons(result))


def field_hints(
    error: ValidationError, hints: Mapping[str, str], unknown: str | None = None
) -> list[str]:
    """Je Feld, das die Prüfung ablehnt, ein Hinweis aus `hints` (Pydantic liefert nur englische
    Meldungen), in der Reihenfolge der Fehler, je Feld einmal. Ein Feld ohne Hinweis (und ein
    Fehler ohne Feld) erhält `unknown`, ohne Angabe den Feldnamen; ein leerer Text entfällt."""
    names = dict.fromkeys(
        next((p for p in reversed(e["loc"]) if isinstance(p, str)), "") for e in error.errors()
    )
    texts = [hints.get(name, name if unknown is None else unknown) for name in names]
    return [text for text in texts if text]


def validated[M: BaseModel](
    model: type[M], data: Mapping[str, Any], hints: Mapping[str, str], unknown: str | None = None
) -> tuple[M | None, list[str]]:
    """Formular -> Modell: das geprüfte Modell, sonst `None` und die Hinweise je Feld."""
    try:
        return model.model_validate(data), []
    except ValidationError as error:
        return None, field_hints(error, hints, unknown)


def _sidebar(request: Request, open_files: int | None) -> list[tuple[str, list[NavEntry]]]:
    """Die Seitenleiste: Module unter „Bereiche“, Belege und Aussteller unter „Allgemein“."""
    registrations: tuple[ModuleRegistration, ...] = request.app.state.modules
    if open_files is None:
        store = store_of(request)
        open_files = len(incoming_files(all_site_files(store), store.state(), user_of(request)))
    areas = [NavEntry(r.nav_label, r.nav_url, r.icon) for r in registrations]
    general = [
        NavEntry("Belege", site_url(), "belege", open_files),
        NavEntry("Aussteller", issuers_url(), "aussteller"),
    ]
    return [("Bereiche", areas), ("Allgemein", general)]


def _findings_summary(request: Request, year: int) -> FindingsSummary:
    visible = values_of(request).finding_list(user_of(request), year).visible  # Fehler zuerst
    counts = {s: sum(1 for f in visible if f.severity is s) for s in reversed(Severity)}
    return FindingsSummary(year, counts, visible[0] if visible else None)


def _year_choices(request: Request, year: int) -> list[int]:
    """Jahre der Kopfleiste: die Bezugsjahre der Dokumente und die Steuerjahre der Einträge des
    Nutzers (jede Eintragsart mit einem Feld `year` meint das Steuerjahr)."""
    user = user_of(request)
    found: set[int] = set()
    for entry in store_of(request).state().entries.values():
        if entry.owner != user:
            continue
        if isinstance(entry, Document):
            if entry.period_start is not None:
                found.add(entry.period_start.year)
        elif isinstance(tax_year := getattr(entry, "year", None), int):
            found.add(tax_year)
    return year_choices(found, year)


def render(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    """Rendert `name`. Den Rahmen (Seitenleiste, Kopfleiste) berechnet `base.html` erst beim
    Gebrauch, Teilvorlagen für htmx kosten ihn nicht. Ein `year` (int) im Kontext übersteuert das
    globale Jahr in der Kopfleiste."""
    templates: Jinja2Templates = request.app.state.templates
    user_name = getattr(request.state, "user_name", None) or user_name_of(request)
    page_year = context.get("year")
    year = page_year if isinstance(page_year, int) else global_year(request)
    open_files: int | None = context.pop("open_files", None)  # die Belege-Seite kennt ihn schon
    shell: dict[str, Callable[[], Any]] = {
        "sidebar": cache(lambda: _sidebar(request, open_files)),
        "findings_summary": cache(lambda: _findings_summary(request, year)),
        "year_choices": cache(lambda: _year_choices(request, year)),
    }
    return templates.TemplateResponse(
        request,
        name,
        {"user_name": user_name, "shell_year": year, **shell, **context},
        status_code=status_code,
    )
