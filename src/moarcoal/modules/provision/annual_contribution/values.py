"""Ausgewiesener Wert der Jahresbeiträge: die über die Basisabsicherung hinausgehenden Beiträge zu
privaten Kranken- und Pflegeversicherungen eines Jahrs abzüglich erstatteter, ungerundet (gerundet
wird erst am Feld der Anlage).

Es zählen die Jahresbeiträge des Jahrs zu Verträgen des Nutzers mit der Steuerlichen Bedeutung
„Kranken- und Pflegeversicherung privat“. Jeder ist ein Einzelposten (Bezeichnung des Vertrags,
Betrag abzüglich Erstattung): Nutzereingabe (angenommen), mit Beleg belegt. Läuft ein solcher
Vertrag im Jahr und hat keinen Jahresbeitrag, ist der Wert noch nicht berechenbar (nie 0); eine
0 € gilt nur, wenn der Nutzer sie als Jahresbeitrag erfasst hat. Gibt es weder einen solchen Vertrag
im Jahr noch einen Jahresbeitrag, entfällt der Wert. Ein einzelner Jahresbeitrag darf mehr
erstattet als gezahlt haben (negativer Einzelposten); ist die Summe negativ, ist der Wert noch nicht
berechenbar (Erstattungsüberhang, § 10 Abs. 4b EStG), nie auf 0 gekappt.
"""

from moarcoal.modules.provision.annual_contribution.changes import contribution_of, net_cents
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.links import provision_url
from moarcoal.modules.provision.meaning import meaning_of, runs_in
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import (
    Amount,
    DocumentLocator,
    Locator,
    Period,
    Source,
    Subject,
    TimeRef,
    Unit,
    UserInputLocator,
    ValueKey,
    format_eur,
)

PRIVATE_HEALTH_EXTRA = ValueKey("provision.private_health_extra")


def _private_health_agreements(state: ModuleState) -> list[Agreement]:
    """Die Verträge des Nutzers mit der Bedeutung Kranken- und Pflegeversicherung privat."""
    found: list[Agreement] = []
    for agreement in state.agreements():
        meaning = meaning_of(state, agreement)
        if meaning is not None and meaning.meaning is TaxMeaning.PRIVATE_HEALTH_CARE:
            found.append(agreement)
    return found


def _private_health_extra(calculation: Calculation) -> Amount:
    year = calculation.year
    state = calculation.own
    agreements = _private_health_agreements(state)
    counted = [(a, contribution_of(state, a, year)) for a in agreements]
    running = [a for a, c in counted if c is None and runs_in(a, year)]
    if running:
        names = ", ".join(a.name for a in running)
        calculation.not_yet(
            f"Für {year} ist kein Jahresbeitrag erfasst zu: {names} "
            "(Kranken- und Pflegeversicherung "
            "privat); eine ausdrückliche 0 € ist ein Wert, Fehlendes nicht"
        )
    contributions = [(a, c) for a, c in counted if c is not None]
    if not contributions:
        calculation.not_applicable(
            f"Kein Vertrag mit der Steuerlichen Bedeutung Kranken- und Pflegeversicherung privat "
            f"läuft {year}, und es ist kein Jahresbeitrag erfasst"
        )
    total = 0
    for agreement, contribution in contributions:
        cents = net_cents(contribution)
        if contribution.refund_cents is None:
            calculation.decide(
                f"{agreement.name}: Betrag {format_eur(contribution.amount_cents)}, "
                "keine Erstattung angegeben"
            )
        else:
            calculation.decide(
                f"{agreement.name}: Betrag {format_eur(contribution.amount_cents)} abzüglich "
                f"Erstattung {format_eur(contribution.refund_cents)}"
            )
        locator: Locator = (
            UserInputLocator(contribution.address)
            if contribution.document is None
            else DocumentLocator(
                contribution.document, Source.PROOF, "annual_contribution", agreement.name
            )
        )
        calculation.item(agreement.name, Amount.eur_cents(cents), locator)
        total += cents
    if total < 0:
        calculation.not_yet(
            f"Die Erstattungen {year} ({format_eur(-total)} mehr als gezahlt) übersteigen die "
            "Jahresbeiträge; bitte prüfen. Ein Erstattungsüberhang wird nach § 10 Abs. 4b EStG "
            "mit anderen Sonderausgaben (Nr. 3a) verrechnet, das kann MoarCoal noch nicht"
        )
    return calculation.step(
        "Summe der Jahresbeiträge abzüglich Erstattungen", Amount.eur_cents(total)
    )


def capture_url(
    key: ValueKey, time: TimeRef, subject: Subject | None, state: ModuleState
) -> tuple[str, str] | None:
    """Wo man den Jahresbeitrag erfasst: die Seite Vorsorge des Jahrs."""
    year = time.calendar_year if isinstance(time, Period) else None
    if key != PRIVATE_HEALTH_EXTRA or year is None:
        return None
    return "Jahresbeitrag erfassen", provision_url(year)


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            PRIVATE_HEALTH_EXTRA,
            "Über die Basisabsicherung hinausgehende Beiträge zu privaten Kranken- und "
            "Pflegeversicherungen eines Jahrs abzüglich erstatteter, laut den Jahresbeiträgen",
            "Beiträge private Kranken-/Pflegeversicherung über die Basisabsicherung hinaus",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _private_health_extra,
    ),
)
