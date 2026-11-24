"""Ausgewiesene Werte der Beitragsbescheinigungen Kranken-/Pflegeversicherung: die Summe der
privaten Beiträge eines Jahrs über alle Bescheinigungen, ungerundet (gerundet wird erst am Feld
der Anlage).

Das Jahr ist das Jahr der Zahlung oder Erstattung (Zuflussprinzip). Mitgezählt werden nur Blöcke
mit dem Merkmal privat; gesetzliche haben ihre eigenen Felder. Noch nicht berechenbar ist ein
Wert, wenn das Jahr keine Bescheinigung hat, eine mit älterer Einlese-Regel eingelesen ist, Pfade
enthält, die die Einlese-Regel nicht kennt, oder einen privaten Block mit unbekanntem Merkmal oder
unbekannter `BetragArt` (die Meldung nennt sie); nichts davon fällt stillschweigend weg.
"""

from moarcoal.modules.provision.health_certificate.entries import (
    Characteristic,
    ContributionKind,
    ContributionLine,
    HealthContributionCertificate,
)
from moarcoal.modules.provision.health_certificate.reading import READER_VERSION
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, DocumentLocator, Source, Unit, ValueKey

HEALTH_BASIC = ValueKey("provision.private_health_basic")
CARE = ValueKey("provision.private_care")
REFUNDS = ValueKey("provision.private_refunds")
STATUTORY_REFUNDS = ValueKey("provision.statutory_refunds")
STATUTORY_REFUNDS_NO_SICK_PAY = ValueKey("provision.statutory_refunds_no_sick_pay")

type Located = tuple[HealthContributionCertificate, ContributionLine]


def _lines(calculation: Calculation, wanted: Characteristic) -> list[Located]:
    """Die Blöcke mit dem Merkmal `wanted` aller Bescheinigungen des Jahrs; sonst noch nicht
    berechenbar."""
    year = calculation.year
    certificates = [c for c in calculation.own.all(HealthContributionCertificate) if c.year == year]
    if not certificates:
        calculation.not_yet(
            f"Für {year} ist keine Beitragsbescheinigung Kranken-/Pflegeversicherung aufgenommen"
        )
    found: list[Located] = []
    for certificate in certificates:
        if certificate.reader_version < READER_VERSION:
            calculation.not_yet(
                f"Eine Beitragsbescheinigung {year} ist mit einer älteren Einlese-Regel "
                "eingelesen; sie wird beim nächsten Start neu eingelesen"
            )
        if certificate.unrecognized:
            calculation.not_yet(
                f"Eine Beitragsbescheinigung {year} enthält Angaben, die MoarCoal nicht kennt "
                f"({', '.join(certificate.unrecognized)}); ob ein Betrag darunter ist, ist offen"
            )
        for line in certificate.lines:
            if line.characteristic is None:
                calculation.not_yet(
                    f"Eine Beitragsbescheinigung {year} nennt das Merkmal „{line.merkmal}“, "
                    "das MoarCoal nicht kennt (privat oder gesetzlich)"
                )
            if line.characteristic is not wanted:
                continue
            if line.kind is None:
                calculation.not_yet(
                    f"Eine Beitragsbescheinigung {year} nennt die Art „{line.art}“, "
                    "die MoarCoal nicht kennt"
                )
            found.append((certificate, line))
    return found


def _total(
    calculation: Calculation,
    kinds: frozenset[ContributionKind],
    label: str,
    *,
    may_be_absent: bool = False,
) -> Amount:
    """Die Summe der privaten Posten der Arten `kinds`, jeder als Einzelposten mit Fundstelle.

    Nennt keine Bescheinigung des Jahrs einen solchen Posten, ist der Wert noch nicht berechenbar,
    außer bei `may_be_absent`: dann sind es 0 €, als Entscheidung im Rechenweg (die Bescheinigungen
    sind vollständig gelesen, so steht fest, dass keiner da ist).
    """
    year = calculation.year
    lines = [
        (c, line) for c, line in _lines(calculation, Characteristic.PRIVATE) if line.kind in kinds
    ]
    if not lines:
        if not may_be_absent:
            calculation.not_yet(f"Keine Beitragsbescheinigung {year} nennt {label}")
        calculation.decide(f"Keine Beitragsbescheinigung {year} nennt {label}: 0 €")
        return calculation.step(f"{label} laut Beitragsbescheinigungen", Amount.eur_cents(0))
    for certificate, line in lines:
        calculation.item(
            line.art,
            Amount.eur_cents(line.cents),
            DocumentLocator(certificate.document, Source.READ_IN, "lines", line.place),
        )
    total = sum(line.cents for _, line in lines)
    return calculation.step(f"{label} laut Beitragsbescheinigungen", Amount.eur_cents(total))


STATUTORY_REFUND_KINDS = frozenset({ContributionKind.HEALTH_REFUND, ContributionKind.CARE_REFUND})
NO_SICK_PAY = "ohne Krankengeldanspruch"  # die erstatteten KV-Beiträge, die in VOR Z. 15 zählen


def _statutory_refunds(calculation: Calculation, label: str, *, no_sick_pay: bool) -> Amount:
    """Die Summe der erstatteten Beiträge der Blöcke mit dem Merkmal gesetzlich (VOR Z. 14, mit
    `no_sick_pay` Z. 15: nur Pflege und Kranken ohne Krankengeldanspruch), jeder als Einzelposten.

    Ohne solchen Block: keine Bescheinigung des Jahrs, noch nicht berechenbar; sind alle Blöcke
    aller Bescheinigungen privat, 0 € (nur privat versichert); sonst nennt keine gesetzliche
    Erstattungen, ebenfalls 0 €. Jede 0 ist eine Entscheidung im Rechenweg.
    """
    year = calculation.year
    lines = [
        (c, line)
        for c, line in _lines(calculation, Characteristic.STATUTORY)
        if line.kind in STATUTORY_REFUND_KINDS
    ]
    if no_sick_pay:
        # Eine Erstattung zur KV mit anderer Schreibweise der Art lässt sich Z. 15 nicht zuordnen.
        for _, line in lines:
            if line.kind is ContributionKind.HEALTH_REFUND and NO_SICK_PAY not in line.art:
                calculation.not_yet(
                    f"Eine Beitragsbescheinigung {year} nennt erstattete Beiträge zur "
                    f"Krankenversicherung als „{line.art}“; ob sie ohne Krankengeldanspruch "
                    "sind, ist offen"
                )
    if not lines:
        certificates = calculation.own.all(HealthContributionCertificate)
        every_line = [line for c in certificates if c.year == year for line in c.lines]
        if all(line.characteristic is Characteristic.PRIVATE for line in every_line):
            calculation.decide(
                f"{label}: 0 €, denn alle Beitragsbescheinigungen {year} sind privat"
            )
        else:
            calculation.decide(
                f"Keine Beitragsbescheinigung {year} nennt {label} der gesetzlichen Versicherung: "
                "0 €"
            )
        return calculation.step(f"{label} laut Beitragsbescheinigungen", Amount.eur_cents(0))
    for certificate, line in lines:
        calculation.item(
            line.art,
            Amount.eur_cents(line.cents),
            DocumentLocator(certificate.document, Source.READ_IN, "lines", line.place),
        )
    total = sum(line.cents for _, line in lines)
    return calculation.step(f"{label} laut Beitragsbescheinigungen", Amount.eur_cents(total))


def _statutory_refunds_all(calculation: Calculation) -> Amount:
    label = "Erstattete Beiträge zur gesetzlichen Kranken- und Pflegeversicherung"
    return _statutory_refunds(calculation, label, no_sick_pay=False)


def _statutory_refunds_no_sick_pay(calculation: Calculation) -> Amount:
    label = "Erstattete Beiträge zur gesetzlichen Krankenversicherung (ohne Krankengeld) und Pflege"
    return _statutory_refunds(calculation, label, no_sick_pay=True)


def _health_basic(calculation: Calculation) -> Amount:
    kinds = frozenset({ContributionKind.HEALTH_BASIC})
    return _total(calculation, kinds, "Beiträge zur Krankenversicherung (Basisleistungen)")


def _care(calculation: Calculation) -> Amount:
    kinds = frozenset({ContributionKind.CARE})
    return _total(calculation, kinds, "Beiträge zur Pflege-Pflichtversicherung")


def _refunds(calculation: Calculation) -> Amount:
    kinds = frozenset({ContributionKind.HEALTH_REFUND, ContributionKind.CARE_REFUND})
    return _total(
        calculation,
        kinds,
        "Erstattete Beiträge zur Kranken- und Pflegeversicherung",
        may_be_absent=True,
    )


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            HEALTH_BASIC,
            "Private Beiträge zur Krankenversicherung (nur Basisleistungen) laut den "
            "Beitragsbescheinigungen des Jahrs",
            "Beiträge private Krankenversicherung (Basisleistungen)",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _health_basic,
    ),
    ValueDefinition(
        CatalogEntry(
            CARE,
            "Private Beiträge zur Pflege-Pflichtversicherung laut den Beitragsbescheinigungen "
            "des Jahrs",
            "Beiträge private Pflege-Pflichtversicherung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _care,
    ),
    ValueDefinition(
        CatalogEntry(
            REFUNDS,
            "Erstattete private Beiträge zur Kranken- und Pflegeversicherung laut den "
            "Beitragsbescheinigungen des Jahrs",
            "Erstattete Beiträge private Kranken-/Pflegeversicherung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _refunds,
    ),
    ValueDefinition(
        CatalogEntry(
            STATUTORY_REFUNDS,
            "Erstattete Beiträge zur gesetzlichen Kranken- und Pflegeversicherung laut den "
            "Beitragsbescheinigungen des Jahrs",
            "Erstattete Beiträge gesetzliche Kranken-/Pflegeversicherung",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _statutory_refunds_all,
    ),
    ValueDefinition(
        CatalogEntry(
            STATUTORY_REFUNDS_NO_SICK_PAY,
            "Davon erstattete Beiträge zur gesetzlichen Krankenversicherung ohne Krankengeld"
            "anspruch und zur sozialen Pflegeversicherung laut den Beitragsbescheinigungen "
            "des Jahrs",
            "Erstattete Beiträge gesetzliche KV (ohne Krankengeld) und soziale PV",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _statutory_refunds_no_sick_pay,
    ),
)
