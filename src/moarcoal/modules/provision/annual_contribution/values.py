"""Ausgewiesene Werte der Jahresbeiträge, einer je Steuerlicher Bedeutung (`ContributionRule`, eine
Rechnung für alle), ungerundet (gerundet wird erst am Feld der Anlage). Z. 27: die über die
Basisabsicherung hinausgehenden Beiträge zu privaten Kranken- und Pflegeversicherungen eines Jahrs
abzüglich erstatteter.

Es zählen die Jahresbeiträge des Jahrs zu Verträgen des Nutzers mit der Steuerlichen Bedeutung
„Kranken- und Pflegeversicherung privat“. Jeder ist ein Einzelposten (Bezeichnung des Vertrags,
Betrag abzüglich Erstattung): Nutzereingabe (angenommen), mit Beleg belegt. Läuft ein solcher
Vertrag im Jahr und hat keinen Jahresbeitrag, ist der Wert noch nicht berechenbar (nie 0); eine
0 € gilt nur, wenn der Nutzer sie als Jahresbeitrag erfasst hat. Gibt es weder einen solchen Vertrag
im Jahr noch einen Jahresbeitrag, entfällt der Wert. Ein einzelner Jahresbeitrag darf mehr
erstattet als gezahlt haben (negativer Einzelposten); ist die Summe negativ, ist der Wert noch nicht
berechenbar (Erstattungsüberhang, § 10 Abs. 4b EStG), nie auf 0 gekappt.

Die Werte für Arbeitslosigkeit, Berufsunfähigkeit und Unfall/Haftpflicht/Risiko (VOR Z. 44 bis 46)
rechnen ebenso, nur ist dort jeder Jahresbeitrag eine eigene Einzelangabe der Anlage: ein negativer
Einzelposten macht den Wert noch nicht berechenbar (auch wenn die Summe positiv bliebe).
"""

from dataclasses import dataclass

from moarcoal.modules.provision.annual_contribution.changes import contribution_of, net_cents
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.links import provision_url
from moarcoal.modules.provision.meaning import agreements_with, runs_in
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
UNEMPLOYMENT = ValueKey("provision.unemployment_contributions")
DISABILITY = ValueKey("provision.disability_contributions")
ACCIDENT_LIABILITY_RISK = ValueKey("provision.accident_liability_risk_contributions")


@dataclass(frozen=True)
class ContributionRule:
    """Ein Wert der Jahresbeiträge: welche Steuerliche Bedeutung er zählt und wie ein negativer
    Betrag wirkt. Die Rechnung ist für alle dieselbe (`_contributions_of`).

    `each_item_non_negative`: Jeder Jahresbeitrag ist eine eigene Einzelangabe der Anlage und
    darf nicht negativ sein (Erstattung größer als Betrag macht den Wert noch nicht berechenbar).
    Sonst zählt nur die Summe (ein einzelner Einzelposten darf negativ sein, die Summe nicht).
    """

    key: ValueKey
    meaning: TaxMeaning
    description: str
    title: str
    each_item_non_negative: bool = False


RULES: tuple[ContributionRule, ...] = (
    ContributionRule(
        PRIVATE_HEALTH_EXTRA,
        TaxMeaning.PRIVATE_HEALTH_CARE,
        "Über die Basisabsicherung hinausgehende Beiträge zu privaten Kranken- und "
        "Pflegeversicherungen eines Jahrs abzüglich erstatteter, laut den Jahresbeiträgen",
        "Beiträge private Kranken-/Pflegeversicherung über die Basisabsicherung hinaus",
    ),
    ContributionRule(
        UNEMPLOYMENT,
        TaxMeaning.UNEMPLOYMENT,
        "Beiträge zu Arbeitslosigkeitsversicherungen eines Jahrs abzüglich erstatteter, "
        "laut den Jahresbeiträgen, je Vertrag",
        "Beiträge Arbeitslosigkeit",
        each_item_non_negative=True,
    ),
    ContributionRule(
        DISABILITY,
        TaxMeaning.DISABILITY,
        "Beiträge zu Berufsunfähigkeitsversicherungen eines Jahrs abzüglich erstatteter, "
        "laut den Jahresbeiträgen, je Vertrag",
        "Beiträge Berufsunfähigkeit",
        each_item_non_negative=True,
    ),
    ContributionRule(
        ACCIDENT_LIABILITY_RISK,
        TaxMeaning.ACCIDENT_LIABILITY_RISK,
        "Beiträge zu Unfall-, Haftpflicht- und Risikoversicherungen eines Jahrs abzüglich "
        "erstatteter, laut den Jahresbeiträgen, je Vertrag",
        "Beiträge Unfall/Haftpflicht/Risiko",
        each_item_non_negative=True,
    ),
)


def _contributions_of(rule: ContributionRule, calculation: Calculation) -> Amount:
    year = calculation.year
    state = calculation.own
    label = rule.meaning.label
    counted = [(a, contribution_of(state, a, year)) for a in agreements_with(state, rule.meaning)]
    running = [a for a, c in counted if c is None and runs_in(a, year)]
    if running:
        names = ", ".join(a.name for a in running)
        calculation.not_yet(
            f"Für {year} ist kein Jahresbeitrag erfasst zu: {names} "
            f"({label}); eine ausdrückliche 0 € ist ein Wert, Fehlendes nicht"
        )
    contributions = [(a, c) for a, c in counted if c is not None]
    if not contributions:
        calculation.not_applicable(
            f"Kein Vertrag mit der Steuerlichen Bedeutung {label} "
            f"läuft {year}, und es ist kein Jahresbeitrag erfasst"
        )
    total = 0
    negative: list[tuple[Agreement, int]] = []
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
        if cents < 0:
            negative.append((agreement, cents))
    if rule.each_item_non_negative and negative:
        details = ", ".join(f"{a.name} ({format_eur(-c)} mehr als gezahlt)" for a, c in negative)
        calculation.not_yet(
            f"Die Erstattungen {year} übersteigen den Jahresbeitrag zu: {details}; bitte prüfen. "
            f"{_OVERHANG}"
        )
    if total < 0:
        calculation.not_yet(
            f"Die Erstattungen {year} ({format_eur(-total)} mehr als gezahlt) übersteigen die "
            f"Jahresbeiträge; bitte prüfen. {_OVERHANG}"
        )
    return calculation.step(
        "Summe der Jahresbeiträge abzüglich Erstattungen", Amount.eur_cents(total)
    )


_OVERHANG = (
    "Ein Erstattungsüberhang wird nach § 10 Abs. 4b EStG mit anderen Sonderausgaben (Nr. 3a) "
    "verrechnet, das kann MoarCoal noch nicht"
)


def capture_url(
    key: ValueKey, time: TimeRef, subject: Subject | None, state: ModuleState
) -> tuple[str, str] | None:
    """Wo man den Jahresbeitrag erfasst: die Seite Vorsorge des Jahrs."""
    year = time.calendar_year if isinstance(time, Period) else None
    if key not in {rule.key for rule in RULES} or year is None:
        return None
    return "Jahresbeitrag erfassen", provision_url(year)


def _definition(rule: ContributionRule) -> ValueDefinition:
    return ValueDefinition(
        CatalogEntry(rule.key, rule.description, rule.title, Unit.EUR, TimeKind.PERIOD),
        lambda calculation: _contributions_of(rule, calculation),
    )


VALUES: tuple[ValueDefinition, ...] = tuple(_definition(rule) for rule in RULES)
