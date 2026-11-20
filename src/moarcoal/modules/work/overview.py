"""Die eine Seite des Moduls Arbeit (`/arbeit`): alle Teile eines Steuerjahrs nebeneinander.

Erste Tätigkeitsstätte, Arbeitsmittel, Lohnsteuerbescheinigung und Dienstreisen stehen auf einer
Seite; bearbeitet wird in aufklappenden Formularen, nicht auf Unterseiten. Jede Antwort der
Seiten des Moduls, auch eine Abweisung, zeigt diese Seite.
"""

from dataclasses import dataclass, replace
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from moarcoal.defaults import year_of
from moarcoal.modules.work.common import MODULE_KEY
from moarcoal.modules.work.trips.view import trips_context
from moarcoal.modules.work.wage_tax.entries import WageTaxCertificate
from moarcoal.modules.work.wage_tax.values import (
    GROSS_WAGES,
    INCOME_TAX_WITHHELD,
    SOLI_WITHHELD,
    TAX_CLASS,
)
from moarcoal.modules.work.workplace.entries import FirstWorkplace, WorkEquipment
from moarcoal.modules.work.workplace.forms import (
    KINDS,
    EntryForm,
    Fields,
    entry_url,
    prefill_from,
    prefill_new,
    useful_life_hint,
)
from moarcoal.modules.work.workplace.values import DISTANCE_KM, EQUIPMENT, WORKDAYS, shares
from moarcoal.storage import Entry, entry_checksum
from moarcoal.values.model import Period
from moarcoal.web.helpers import module_state, render, user_of, values_of
from moarcoal.web.links import document_url


@dataclass(frozen=True)
class EntryFormView:
    """Ein Formular der Seite: zu einem Eintrag (`entry_id`) oder neu (leer); `open` = offen."""

    kind: EntryForm
    entry_id: str
    checksum: str
    values: Fields
    errors: tuple[str, ...] = ()
    open: bool = False

    @property
    def useful_life_hint(self) -> str:
        return useful_life_hint(year_of(self.values.get("year", ""), in_range=True))

    @property
    def action(self) -> str:
        base = f"/arbeit/{self.kind.slug}"
        return f"{base}/{self.entry_id}" if self.entry_id else base


def submitted(kind: EntryForm, entry_id: str, fields: Fields, errors: list[str]) -> EntryFormView:
    """Ein abgeschicktes, abgewiesenes Formular: Eingabe und Gründe bleiben stehen, es ist offen."""
    return EntryFormView(kind, entry_id, fields.get("checksum", ""), fields, tuple(errors), True)


def _forms(
    entries: list[Entry], kind: EntryForm, open_entry: str, sent: EntryFormView | None
) -> list[EntryFormView]:
    """Je Eintrag sein Formular, vorbelegt aus dem Eintrag; das abgeschickte ersetzt seines."""
    forms: list[EntryFormView] = []
    for entry in entries:
        form = EntryFormView(
            kind, entry.id, entry_checksum(entry), prefill_from(entry), open=entry.id == open_entry
        )
        if sent is not None and (sent.kind.slug, sent.entry_id) == (kind.slug, entry.id):
            form = replace(sent, checksum=sent.checksum or form.checksum)
        forms.append(form)
    return forms


def _new_form(kind: EntryForm, year: int, sent: EntryFormView | None) -> EntryFormView:
    if sent is not None and sent.kind.slug == kind.slug and not sent.entry_id:
        return sent
    return EntryFormView(kind, "", "", prefill_new(kind.slug, year))


def _wage_tax(request: Request, year: int) -> dict[str, Any]:
    """Die Werte der Lohnsteuerbescheinigung des Jahrs, genau wie eingelesen, mit Link zum Beleg."""
    period = Period.year(year)
    values = values_of(request)
    user = user_of(request)
    certificates = [
        c for c in module_state(request, MODULE_KEY).all(WageTaxCertificate) if c.year == year
    ]
    return {
        "values": [
            (label, values.get(key, user, period))
            for label, key in (
                ("Steuerklasse", TAX_CLASS),
                ("Bruttoarbeitslohn", GROSS_WAGES),
                ("Lohnsteuer", INCOME_TAX_WITHHELD),
                ("Solidaritätszuschlag", SOLI_WITHHELD),
            )
        ],
        "documents": [document_url(c.document.id) for c in certificates],
    }


def work_page(
    request: Request,
    year: int,
    status_code: int = 200,
    *,
    open_entry: str = "",
    sent: EntryFormView | None = None,
    **trips: Any,
) -> HTMLResponse:
    """Die Seite Arbeit für `year`. `open_entry` klappt den Eintrag auf, `sent` zeigt ein
    abgewiesenes Formular; `trips` geht an die Dienstreisen (Zeilen, Fehler, Ortssuche)."""
    state = module_state(request, MODULE_KEY)
    period = Period.year(year)
    values = values_of(request)
    user = user_of(request)
    workplaces = [e for e in state.all(FirstWorkplace) if e.year == year]
    equipment = sorted(
        (e for e in state.all(WorkEquipment) if e.year == year), key=lambda e: e.input.date
    )
    counted = shares(state, year)
    share_of = {purchase.id: share for purchase, share in counted}
    place, gear = KINDS["erste-taetigkeitsstaette"], KINDS["arbeitsmittel"]
    return render(
        request,
        "work/index.html",
        status_code,
        workplaces=list(
            zip(
                workplaces,
                _forms(list(workplaces), place, open_entry, sent),
                values.all(WORKDAYS, user, period),
                values.all(DISTANCE_KM, user, period),
                strict=True,
            )
        ),
        new_workplace=_new_form(place, year, sent),
        equipment=[
            (entry, form, share_of.get(entry.id))
            for entry, form in zip(
                equipment, _forms(list(equipment), gear, open_entry, sent), strict=True
            )
        ],
        running=[(p, share, entry_url(p.address)) for p, share in counted if p.year < year],
        new_equipment=_new_form(gear, year, sent),
        equipment_total=values.get(EQUIPMENT, user, period),
        wage_tax=_wage_tax(request, year),
        **trips_context(request, year, **trips),
    )
