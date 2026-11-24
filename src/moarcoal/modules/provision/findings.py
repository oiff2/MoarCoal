"""Befunde des Moduls Vorsorge: eine eingelesene Bescheinigung ohne passenden Vertrag und ein
Vertrag ohne Bescheinigung. Die Zuordnung ist die der Seite (`certificate_rows`, `pension_rows`);
dazu kommt die Steuerliche Bedeutung. Rein: Stand rein, Befunde raus. Ein Befund nennt nie die
Vertragsnummer."""

from collections.abc import Sequence

from moarcoal.modules.provision.basic_pension.view import pension_rows
from moarcoal.modules.provision.entries import TaxMeaning
from moarcoal.modules.provision.health_certificate.view import certificate_rows
from moarcoal.modules.provision.links import provision_url
from moarcoal.modules.provision.meaning import agreements_with, meaning_of, running_agreements
from moarcoal.registration import ModuleState
from moarcoal.storage import Agreement, EntryAddress
from moarcoal.values.calculation import ValueSource
from moarcoal.values.findings import Finding, FindingKind, Severity

CERTIFICATE_WITHOUT_AGREEMENT = "provision.certificate_without_agreement"
AGREEMENT_WITHOUT_CERTIFICATE = "provision.agreement_without_certificate"

FINDING_KINDS = (
    FindingKind(CERTIFICATE_WITHOUT_AGREEMENT, "Bescheinigung ohne Vertrag"),
    FindingKind(AGREEMENT_WITHOUT_CERTIFICATE, "Vertrag ohne Bescheinigung"),
)


def has_meaning(state: ModuleState, agreement: Agreement, meaning: TaxMeaning) -> bool:
    found = meaning_of(state, agreement)
    return found is not None and found.meaning is meaning


def provision_findings(state: ModuleState, values: ValueSource, year: int) -> list[Finding]:
    """Hinweise für `year`: je Bescheinigung ohne zugeordneten Vertrag mit der passenden
    Bedeutung, je laufenden Vertrag mit Bedeutung Kranken- und Pflegeversicherung privat oder
    Basisrente ohne zugeordnete Bescheinigung."""
    running = running_agreements(state.agreements(), year)
    health = certificate_rows(state, year, running)
    pensions = pension_rows(state, year, state.agreements())
    found: list[Finding] = []
    for row in health:
        if row.has_private_block and not any(
            has_meaning(state, a, TaxMeaning.PRIVATE_HEALTH_CARE) for a in row.agreements
        ):
            found.append(
                _without_agreement(
                    row.certificate.address,
                    f"Die Beitragsbescheinigung Kranken-/Pflegeversicherung {year} hat keinen "
                    "Vertrag ihres Ausstellers mit der Steuerlichen Bedeutung "
                    f"„{TaxMeaning.PRIVATE_HEALTH_CARE.label}“.",
                    year,
                    "vorsorge-bescheinigungen",
                )
            )
    for pension in pensions:
        if not any(has_meaning(state, a, TaxMeaning.BASIC_PENSION) for a in pension.agreements):
            found.append(
                _without_agreement(
                    pension.certificate.address,
                    f"Die Anbieterbescheinigung Basisrente {year} hat keinen Vertrag mit "
                    "ihrer Vertragsnummer und der Steuerlichen Bedeutung "
                    f"„{TaxMeaning.BASIC_PENSION.label}“.",
                    year,
                    "vorsorge-basisrente",
                )
            )
    covered_health = {a.address for row in health for a in row.agreements}
    covered_pension = {a.address for row in pensions for a in row.agreements}
    found.extend(
        _without_certificate(a, year, TaxMeaning.PRIVATE_HEALTH_CARE, "Beitragsbescheinigung")
        for a in _running_with(state, running, TaxMeaning.PRIVATE_HEALTH_CARE)
        if a.address not in covered_health
    )
    found.extend(
        _without_certificate(a, year, TaxMeaning.BASIC_PENSION, "Anbieterbescheinigung")
        for a in _running_with(state, running, TaxMeaning.BASIC_PENSION)
        if a.address not in covered_pension
    )
    return found


def _running_with(
    state: ModuleState, running: Sequence[Agreement], meaning: TaxMeaning
) -> list[Agreement]:
    with_meaning = {a.address for a in agreements_with(state, meaning)}
    return [a for a in running if a.address in with_meaning]


def _without_agreement(target: EntryAddress, message: str, year: int, section: str) -> Finding:
    href = f"{provision_url(year)}#{section}"
    return Finding(CERTIFICATE_WITHOUT_AGREEMENT, Severity.NOTE, target, message, href=href)


def _without_certificate(
    agreement: Agreement, year: int, meaning: TaxMeaning, certificate: str
) -> Finding:
    message = (
        f"Der Vertrag „{agreement.name}“ ({meaning.label}) läuft {year}, aber es ist keine "
        f"{certificate} {year} zugeordnet."
    )
    # das Jahr im Ziel: ein Befund je Vertrag und Jahr, ausgeblendet gilt er nur für dieses Jahr
    return Finding(
        AGREEMENT_WITHOUT_CERTIFICATE,
        Severity.NOTE,
        f"{agreement.address}@{year}",
        message,
        href=f"{provision_url(year)}#vorsorge-vertraege",
    )
