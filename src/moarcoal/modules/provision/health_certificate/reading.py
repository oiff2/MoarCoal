"""Einlese-Regel der Beitragsbescheinigung Kranken-/Pflegeversicherung (eDaten-HTML,
`Belegart: VaSt_KRV`), ohne Claude.

Den Leser des HTML teilen alle Dokumentarten dieses Formats (`modules/elster_html.py`). Die Datei
hat mehrere Blöcke `Vertragsdaten-Beitragsdaten`; der Index der Wiederholgruppe (`…_1-1-<n>-1`)
fasst die Felder eines Blocks zusammen: `MerkmalBeiTrag` (privat oder gesetzlich), `BetragArt`,
`Beginn`, `Ende`, `Waehrung` und `Betrag`. Jeder Block wird eine Zeile des Eintrags, mit dem
Betrag in Cent und seiner Fundstelle; summiert wird erst bei den Werten (`values.py`).

Die `BetragArt` wird wörtlich festgehalten und, soweit sie bekannt ist (`CONTRIBUTION_KINDS`),
einem Beitragsposten zugeordnet; eine unbekannte bleibt ohne Zuordnung und macht die Werte noch
nicht berechenbar, statt dass ein Block stillschweigend wegfällt. Dasselbe gilt für jeden Pfad
der Datei, den die Einlese-Regel nicht kennt (`KNOWN_PATHS`). Was die Datei nicht nennt, steht
nicht im Eintrag (nie 0). Ein Block, dem `MerkmalBeiTrag`, `BetragArt` oder `Betrag` fehlt, eine
andere Währung als Euro oder ein Zeitraum außerhalb des Jahrs des Dokuments (Zuflussprinzip: das
Jahr der Zahlung oder Erstattung gilt) weist die Datei ab, statt zu raten.
"""

import datetime
from collections.abc import Mapping

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
    unrecognized_paths,
)
from moarcoal.modules.provision.health_certificate.entries import (
    Characteristic,
    ContributionKind,
    ContributionLine,
    HealthContributionCertificate,
)
from moarcoal.storage import Document, ReadInEntry, unique_by_issuer

READER_VERSION = 1
TITLE = "Beitragsbescheinigung Kranken-/Pflegeversicherung"  # Titel der Dokumentart
BELEGART = "VaSt_KRV"

BLOCK = "Vertragsdaten-Beitragsdaten"
CHARACTERISTIC = "MerkmalBeiTrag"
ART = "BetragArt"
START = "Beginn"
END = "Ende"
CURRENCY = "Waehrung"
AMOUNT = "Betrag"
BLOCK_FIELDS = (CHARACTERISTIC, ART, START, END, CURRENCY, AMOUNT)
REQUIRED = {CHARACTERISTIC: "Merkmal", ART: "Art des Betrags", AMOUNT: "Betrag"}

# Pfade, die die Einlese-Regel kennt (ohne `VaSt_KRV-` und Index): die Felder der Blöcke und der
# Kopf wie in den übrigen eDaten-Belegen.
KNOWN_PATHS = frozenset({*(f"{BLOCK}-{name}" for name in BLOCK_FIELDS), *HEADER_PATHS})

# `BetragArt` (Leerraum vereinheitlicht) -> Beitragsposten; ein Eintrag gilt für genau diese
# Schreibweise, bei `PREFIXES` für jede, die so beginnt.
CONTRIBUTION_KINDS: Mapping[str, ContributionKind] = {
    "Geleistete Beiträge zur Krankenversicherung (ohne Krankengeldanspruch) "
    "ohne Zusatzbeitrag für Basisleistungen": ContributionKind.HEALTH_BASIC,
    "Geleistete Beiträge zur sozialen oder privaten Pflegepflichtversicherung": (
        ContributionKind.CARE
    ),
}
PREFIXES: Mapping[str, ContributionKind] = {
    "Erstattete Beiträge zur Krankenversicherung": ContributionKind.HEALTH_REFUND,
    "Erstattete Beiträge zur sozialen oder privaten Pflegepflichtversicherung": (
        ContributionKind.CARE_REFUND
    ),
}
CHARACTERISTICS: Mapping[str, Characteristic] = {
    "privat": Characteristic.PRIVATE,
    "gesetzlich": Characteristic.STATUTORY,
}


def contribution_kind(art: str) -> ContributionKind | None:
    """Der Beitragsposten zur `BetragArt`; `None`, wenn MoarCoal sie nicht kennt."""
    normalized = " ".join(art.split())
    if normalized in CONTRIBUTION_KINDS:
        return CONTRIBUTION_KINDS[normalized]
    return next((kind for prefix, kind in PREFIXES.items() if normalized.startswith(prefix)), None)


def _date(field: HtmlField, name: str, year: int) -> datetime.date:
    """Das Datum (TT.MM.JJJJ oder JJJJ-MM-TT) im Jahr des Dokuments; sonst `ReadInError`."""
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            date = datetime.datetime.strptime(field.text, pattern).date()
        except ValueError:
            continue
        if date.year != year:
            raise ReadInError(
                f"{name}: „{field.text}“ liegt nicht im Jahr {year}, für das das Dokument "
                "eingetragen ist; es zählt das Jahr der Zahlung oder Erstattung."
            )
        return date
    raise ReadInError(f"{name}: „{field.text}“ ist kein Datum (TT.MM.JJJJ).")


def _line(block: dict[str, HtmlField], number: int, year: int) -> ContributionLine:
    require_fields(block, REQUIRED, f"Beitragsdaten {number}")
    require_euro(block.get(CURRENCY), f"Beitragsdaten {number}")
    merkmal = block[CHARACTERISTIC].text
    art = " ".join(block[ART].text.split())
    return ContributionLine(
        art=art,
        kind=contribution_kind(art),
        merkmal=merkmal,
        characteristic=CHARACTERISTICS.get(merkmal.strip().lower()),
        cents=read_cents(block[AMOUNT], f"Beitragsdaten {number}: Betrag"),
        start=_date(block[START], f"Beitragsdaten {number}: Beginn", year)
        if START in block
        else None,
        end=_date(block[END], f"Beitragsdaten {number}: Ende", year) if END in block else None,
        place=block[AMOUNT].data_name,
    )


def read_in_health_contribution_certificate(
    document: Document, content: bytes
) -> list[ReadInEntry]:
    """Einlese-Regel der Dokumentart Beitragsbescheinigung Kranken-/Pflegeversicherung."""
    year, parsed = parse_elster_document(document, content, BELEGART, TITLE)
    fields = list(parsed.fields)
    blocks = blocks_of(fields, BELEGART, BLOCK)
    if not blocks:
        raise ReadInError(
            "Die Datei nennt keine Beitragsdaten (Vertragsdaten-Beitragsdaten); "
            "keine Beitragsbescheinigung?"
        )
    try:
        entry = HealthContributionCertificate(
            owner=document.owner,
            document=document.address,
            year=year,
            reader_version=READER_VERSION,
            lines=tuple(_line(block, n, year) for n, block in enumerate(blocks, start=1)),
            unrecognized=unrecognized_paths(fields, BELEGART, KNOWN_PATHS),
        )
    except ValidationError as error:
        raise ReadInError(
            "Ein Wert der Beitragsbescheinigung liegt außerhalb des Bereichs."
        ) from error
    return [entry]


HEALTH_CONTRIBUTION_CERTIFICATE = DocumentKind(
    key="health_contribution_certificate",
    title=TITLE,
    has_period=True,
    read_in=read_in_health_contribution_certificate,
    reader_version=READER_VERSION,
    unique_per_period=True,
    unique_by=unique_by_issuer,
)
