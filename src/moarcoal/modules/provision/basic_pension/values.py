"""Ausgewiesener Wert der Anbieterbescheinigungen Basisrente: die Summe der Beiträge eines Jahrs
über alle Bescheinigungen, ungerundet (gerundet wird erst am Feld der Anlage).

Das Jahr ist das Zahljahr (Zuflussprinzip). Jeder Beitragsblock ist ein Einzelposten mit der
Fundstelle im Dokument; die Vertragsnummer steht nirgends im Rechenweg, und der Wert hängt nicht
davon ab, ob die Bescheinigung einem Vertrag zugeordnet ist. Noch nicht berechenbar ist er, wenn
das Jahr keine Bescheinigung hat, eine mit älterer Einlese-Regel eingelesen ist oder Pfade
enthält, die die Einlese-Regel nicht kennt; nichts davon fällt stillschweigend weg.
"""

from moarcoal.modules.provision.basic_pension.entries import BasicPensionCertificate
from moarcoal.modules.provision.basic_pension.reading import READER_VERSION
from moarcoal.modules.provision.common import require_current_reading
from moarcoal.values.calculation import Calculation
from moarcoal.values.catalog import CatalogEntry, TimeKind, ValueDefinition
from moarcoal.values.model import Amount, DocumentLocator, Source, Unit, ValueKey

BASIC_PENSION = ValueKey("provision.basic_pension")


def _basic_pension(calculation: Calculation) -> Amount:
    year = calculation.year
    certificates = [c for c in calculation.own.all(BasicPensionCertificate) if c.year == year]
    if not certificates:
        calculation.not_yet(f"Für {year} ist keine Anbieterbescheinigung Basisrente aufgenommen")
    total = 0
    for certificate in certificates:
        require_current_reading(
            calculation,
            "Eine Anbieterbescheinigung Basisrente",
            year,
            reader_version=certificate.reader_version,
            current_version=READER_VERSION,
            unrecognized=certificate.unrecognized,
        )
        for line in certificate.lines:
            locator = DocumentLocator(certificate.document, Source.READ_IN, "lines", line.place)
            calculation.item("Beitrag zur Basisrente", Amount.eur_cents(line.cents), locator)
            total += line.cents
    return calculation.step(
        "Beiträge zu Basisrentenverträgen laut Anbieterbescheinigungen", Amount.eur_cents(total)
    )


VALUES: tuple[ValueDefinition, ...] = (
    ValueDefinition(
        CatalogEntry(
            BASIC_PENSION,
            "Beiträge zu zertifizierten Basisrentenverträgen laut den Anbieterbescheinigungen "
            "des Jahrs",
            "Beiträge Basisrente",
            Unit.EUR,
            TimeKind.PERIOD,
        ),
        _basic_pension,
    ),
)
