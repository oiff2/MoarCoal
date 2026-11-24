"""Einlese-Regel der Anbieterbescheinigung Basisrente (eDaten-HTML, `Belegart: VaSt_RUE`),
ohne Claude.

Den Leser des HTML und die Teile für Blöcke teilen alle Dokumentarten dieses Formats
(`modules/elster_html.py`). Im Kopf stehen die Vertragsnummer (`Vertragsdaten-VertragsNr`) und die
Zertifizierungsnummer; die Beiträge stehen in Blöcken `Vertragsdaten-Beitragsdaten` (Zahljahr,
Währung, Betrag). Jeder Block wird eine Zeile des Eintrags, mit dem Betrag in Cent und seiner
Fundstelle; summiert wird erst bei den Werten (`values.py`).

Jeder Pfad der Datei, den die Einlese-Regel nicht kennt (`KNOWN_PATHS`), macht die Werte noch nicht
berechenbar, statt dass ein Wert stillschweigend wegfällt. Ohne Vertragsnummer, ohne Beitragsblock,
ohne Zahljahr oder Betrag in einem Block, mit anderer Währung als Euro oder einem Zahljahr, das
nicht das Jahr des Dokuments ist (Zuflussprinzip), weist die Datei ab, statt zu raten. Die
Meldungen nennen nie die Vertragsnummer.
"""

from collections.abc import Hashable, Mapping

from pydantic import ValidationError

from moarcoal.documents import DocumentKind, ReadInError
from moarcoal.modules.elster_html import (
    HEADER_PATHS,
    HtmlField,
    blocks_of,
    parse_elster_document,
    read_cents,
    require_euro,
    require_fields,
    single_field,
    unrecognized_paths,
)
from moarcoal.modules.provision.basic_pension.entries import BasicPensionCertificate, PensionLine
from moarcoal.storage import Document, Entry, EntryAddress, ReadInEntry, number_key

READER_VERSION = 1
TITLE = "Anbieterbescheinigung Basisrente"  # Titel der Dokumentart
BELEGART = "VaSt_RUE"

CONTRACT = "Vertragsdaten-VertragsNr"
CERTIFICATION = "Vertragsdaten-ZertifizierungsNr"
BLOCK = "Vertragsdaten-Beitragsdaten"
PAID_YEAR = "Zahljahr"
CURRENCY = "Waehrung"
AMOUNT = "Betrag"
BLOCK_FIELDS = (PAID_YEAR, CURRENCY, AMOUNT)
REQUIRED = {PAID_YEAR: "Zahljahr", AMOUNT: "Betrag"}

# Pfade, die die Einlese-Regel kennt (ohne `VaSt_RUE-` und Index).
KNOWN_PATHS = frozenset(
    {CONTRACT, CERTIFICATION, *(f"{BLOCK}-{name}" for name in BLOCK_FIELDS), *HEADER_PATHS}
)


def _paid_year(field: HtmlField, number: int, year: int) -> int:
    """Das Zahljahr eines Blocks; es muss das Jahr des Dokuments sein."""
    text = field.text.strip()
    if not text.isdigit() or int(text) != year:
        raise ReadInError(
            f"Beitragsdaten {number}: Zahljahr „{field.text}“ ist nicht das Jahr {year}, für das "
            "das Dokument eingetragen ist; es zählt das Jahr der Zahlung."
        )
    return year


def _line(block: Mapping[str, HtmlField], number: int, year: int) -> PensionLine:
    where = f"Beitragsdaten {number}"
    require_fields(block, REQUIRED, where)
    require_euro(block.get(CURRENCY), where)
    return PensionLine(
        paid_year=_paid_year(block[PAID_YEAR], number, year),
        cents=read_cents(block[AMOUNT], f"{where}: Betrag"),
        place=block[AMOUNT].data_name,
    )


def read_in_basic_pension_certificate(document: Document, content: bytes) -> list[ReadInEntry]:
    """Einlese-Regel der Dokumentart Anbieterbescheinigung Basisrente."""
    year, parsed = parse_elster_document(document, content, BELEGART, TITLE)
    fields = list(parsed.fields)
    contract = single_field(fields, BELEGART, CONTRACT, "Vertragsnummer")
    if contract is None or not contract.text.strip():
        raise ReadInError("Die Datei nennt keine Vertragsnummer (Vertragsdaten-VertragsNr).")
    certification = single_field(fields, BELEGART, CERTIFICATION, "Zertifizierungsnummer")
    blocks = blocks_of(fields, BELEGART, BLOCK)
    if not blocks:
        raise ReadInError(
            "Die Datei nennt keine Beitragsdaten (Vertragsdaten-Beitragsdaten); "
            "keine Anbieterbescheinigung?"
        )
    lines = tuple(_line(block, n, year) for n, block in enumerate(blocks, start=1))
    try:
        entry = BasicPensionCertificate(
            owner=document.owner,
            document=document.address,
            year=year,
            reader_version=READER_VERSION,
            contract_number=contract.text.strip(),
            certification_number=(certification.text.strip() or None) if certification else None,
            lines=lines,
            unrecognized=unrecognized_paths(fields, BELEGART, KNOWN_PATHS),
        )
    except ValidationError:
        # Ohne Verkettung: die Fehlermeldung von pydantic nennt die Eingabewerte, auch die Nummer.
        raise ReadInError(
            "Ein Wert der Anbieterbescheinigung liegt außerhalb des Bereichs."
        ) from None
    return [entry]


def contract_key(document: Document, entries: Mapping[EntryAddress, Entry]) -> Hashable:
    """Eindeutigkeitsschlüssel der Dokumentart (`DocumentKind.unique_by`): die Vertragsnummer der
    eingelesenen Bescheinigung, ohne Groß-/Kleinschreibung und Leerraum. Ohne Einlesung kollidiert
    das Dokument mit keinem."""
    for entry in entries.values():
        if isinstance(entry, BasicPensionCertificate) and entry.document == document.address:
            return number_key(entry.contract_number)
    return document.address


BASIC_PENSION_CERTIFICATE = DocumentKind(
    key="basic_pension_certificate",
    title=TITLE,
    has_period=True,
    read_in=read_in_basic_pension_certificate,
    reader_version=READER_VERSION,
    unique_per_period=True,
    unique_by=contract_key,
)
