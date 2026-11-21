"""Übernahme aus Kohlebau: liest den Quellordner von Kohlebau und schreibt nur über `Store.apply`.

Aufruf (das Datenverzeichnis ist Pflicht, damit nie versehentlich das echte beschrieben wird):

    uv run python tools/kohlebau_import.py <Kohlebau-Quellordner> --data-dir <Datenverzeichnis>
        [--year 2025] [--user ich]

Gelesen wird, was Kohlebau im Quellordner ablegt: `aussteller.json` (Aussteller mit Aliassen und
früheren Kennungen) und `<jahr>/.kohlebau/steuerjahr.json` (Schlüssel `belege`: Art, Belegtyp,
Aussteller, Pfad, Prüfsumme). Feldwerte, Bescheid-Positionen und Dienstreisen werden nicht gelesen.

Teile: Aussteller, dann Belege. Weitere Teile (Verträge, Freistellungsbeträge, Immobilie) hängen
sich an `PARTS` an: jeder liest `Source`, schreibt über `store.apply` und meldet in `Report`.

Wiederholbar: ein vorhandener Aussteller (Name oder Alias) wird erkannt, eine schon aufgenommene
Datei (SHA-256) auch; ein zweiter Lauf ändert nichts. Die Ausgabe nennt Aussteller mit Namen, damit
der Nutzer die Liste prüfen kann, Belege nur mit der Kennung aus Kohlebau, nie Pfade oder Werte.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from moarcoal.defaults import DEFAULT_USER, DEFAULT_YEAR, year_of
from moarcoal.documents import IntakeRejected, take_in
from moarcoal.incoming import all_site_files
from moarcoal.modules import MODULES
from moarcoal.modules.tax_year import TRANSFER_PROTOCOL
from moarcoal.modules.tax_year.assessment import ASSESSMENT
from moarcoal.modules.work.wage_tax.reading import WAGE_TAX_CERTIFICATE
from moarcoal.registration import ModuleRegistration, open_module_store
from moarcoal.storage import (
    COMMON_OWNER,
    Applied,
    Document,
    EntryAddress,
    Issuer,
    PersonalDetails,
    Put,
    Rejected,
    Store,
    entry_checksum,
    name_key,
)
from moarcoal.storage.documents import documents_of_file
from moarcoal.storage.issuers import issuer_with_name
from moarcoal.values.engine import Values

OWN_ISSUER_ID = "selbst"  # Kohlebaus Aussteller für Eigenbelege
SHA256_PREFIX = "sha256:"

# Kohlebau-Art -> Schlüssel der Dokumentart in MoarCoal; die Art „beleg“ hängt vom Belegtyp ab.
KIND_BY_ART: Mapping[str, str] = {
    "bescheid": ASSESSMENT.key,
    "uebertragungsprotokoll": TRANSFER_PROTOCOL.key,
}
# Kohlebau-Belegtyp (Art „beleg“) -> Dokumentart; was fehlt, bleibt ein Beleg ohne Art.
KIND_BY_DOCUMENT_TYPE: Mapping[str, str] = {
    "Lohnsteuerbescheinigung": WAGE_TAX_CERTIFICATE.key,
}


class SourceError(Exception):
    """Der Kohlebau-Ordner lässt sich nicht lesen; die Meldung ist für den Nutzer."""


@dataclass(frozen=True)
class KohlebauIssuer:
    id: str
    name: str
    aliases: tuple[str, ...]
    former_ids: tuple[str, ...]


@dataclass(frozen=True)
class KohlebauDocument:
    id: str
    art: str | None
    document_type: str
    issuer_id: str
    sha256: str


@dataclass(frozen=True)
class Source:
    """Was aus Kohlebau gelesen ist."""

    year: int
    issuers: tuple[KohlebauIssuer, ...]
    documents: tuple[KohlebauDocument, ...]


@dataclass
class Report:
    """Was übernommen, übersprungen und gemeldet wurde: Zähler je Stichwort und Meldungen."""

    counts: dict[str, int] = field(default_factory=dict[str, int])
    notes: list[str] = field(default_factory=list[str])

    def count(self, key: str, note: str | None = None) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1
        if note is not None:
            self.notes.append(note)

    def lines(self) -> list[str]:
        return [*self.notes, *(f"{key}: {number}" for key, number in sorted(self.counts.items()))]


@dataclass
class Context:
    store: Store
    modules: Sequence[ModuleRegistration]
    user: str
    issuers: dict[str, EntryAddress | None] = field(
        default_factory=dict[str, EntryAddress | None]
    )  # Kohlebau-Id -> Adresse


type Part = Callable[[Context, Source, Report], None]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SourceError(f"{path.name} nicht lesbar ({type(error).__name__}).") from error
    if not isinstance(data, dict):
        raise SourceError(f"{path.name} hat nicht die erwartete Form.")
    return data  # pyright: ignore[reportUnknownVariableType]


def _items(data: Mapping[str, Any], key: str, file: str) -> list[Mapping[str, Any]]:
    items = data.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):  # pyright: ignore[reportUnknownVariableType]
        raise SourceError(f"{file}: „{key}“ hat nicht die erwartete Form.")
    return items  # pyright: ignore[reportUnknownVariableType]


def _text(item: Mapping[str, Any], key: str, file: str, *, required: bool = True) -> str:
    value = item.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise SourceError(f"{file}: ein Eintrag hat kein gültiges „{key}“.")
    return value.strip()


def _texts(item: Mapping[str, Any], key: str, file: str) -> tuple[str, ...]:
    values: object = item.get(key, [])
    if not isinstance(values, list):
        raise SourceError(f"{file}: „{key}“ hat nicht die erwartete Form.")
    texts = [v for v in cast("list[object]", values) if isinstance(v, str)]
    if len(texts) != len(cast("list[object]", values)):
        raise SourceError(f"{file}: „{key}“ hat nicht die erwartete Form.")
    return tuple(v.strip() for v in texts if v.strip())


def read_source(root: Path, year: int) -> Source:
    """Liest Aussteller und Belege des Jahrs aus dem Kohlebau-Quellordner."""
    issuer_file = "aussteller.json"
    issuers = tuple(
        KohlebauIssuer(
            id=_text(item, "id", issuer_file),
            name=_text(item, "name", issuer_file),
            aliases=_texts(item, "aliasse", issuer_file),
            former_ids=_texts(item, "fruehere_ids", issuer_file),
        )
        for item in _items(_read_json(root / issuer_file), "aussteller", issuer_file)
    )
    year_file = "steuerjahr.json"
    year_data = _read_json(root / str(year) / ".kohlebau" / year_file)
    documents: list[KohlebauDocument] = []
    for item in _items(year_data, "belege", year_file):
        checksum = _text(item, "pruefsumme", year_file)
        art = _text(item, "art", year_file, required=False)
        documents.append(
            KohlebauDocument(
                id=_text(item, "id", year_file),
                art=art or None,
                document_type=_text(item, "belegtyp", year_file, required=False),
                issuer_id=_text(item, "aussteller", year_file, required=False),
                sha256=checksum.removeprefix(SHA256_PREFIX).lower(),
            )
        )
    return Source(year, issuers, tuple(documents))


def _own_issuer(ctx: Context) -> EntryAddress | None:
    """Der Aussteller aus den Angaben zur Person des Nutzers (für Kohlebaus „selbst“)."""
    for details in ctx.store.state().of_kind(PersonalDetails):
        if details.owner == ctx.user:
            return details.issuer
    return None


def import_issuers(ctx: Context, source: Source, report: Report) -> None:
    """Bildet jeden Kohlebau-Aussteller auf einen vorhandenen ab (Name oder Alias) oder legt ihn an.

    Mehrdeutige Treffer (Namen, die zu verschiedenen Ausstellern gehören) werden gemeldet und
    übersprungen; Belege dieses Ausstellers kommen ohne Aussteller auf.
    """
    own = _own_issuer(ctx)
    for kohlebau in source.issuers:
        if kohlebau.id == OWN_ISSUER_ID:
            ctx.issuers[kohlebau.id] = own
            if own is None:
                report.count(
                    "Aussteller selbst ohne Angaben zur Person",
                    "Aussteller „selbst“: keine Angaben zur Person.",
                )
            else:
                report.count("Aussteller selbst")
            continue
        names = [kohlebau.name, *kohlebau.aliases]
        issuers = ctx.store.state().of_kind(Issuer)
        holders = {h.id: h for n in names if (h := issuer_with_name(issuers, n)) is not None}
        if len(holders) > 1:
            ctx.issuers[kohlebau.id] = None
            report.count(
                "Aussteller mehrdeutig", f"Aussteller mehrdeutig, übersprungen: {kohlebau.name}"
            )
            continue
        if holders:
            ctx.issuers[kohlebau.id] = next(iter(holders.values())).address
            report.count("Aussteller vorhanden")
            continue
        aliases = tuple(
            dict.fromkeys(a for a in kohlebau.aliases if name_key(a) != name_key(kohlebau.name))
        )
        created = Issuer(owner=COMMON_OWNER, name=kohlebau.name, aliases=aliases)
        result = ctx.store.apply([Put(created)])
        if isinstance(result, Applied):
            ctx.issuers[kohlebau.id] = created.address
            report.count("Aussteller angelegt", f"Aussteller angelegt: {kohlebau.name}")
        else:
            ctx.issuers[kohlebau.id] = None
            reasons = "; ".join(result.reasons.values())
            report.count(
                "Aussteller abgewiesen", f"Aussteller abgewiesen: {kohlebau.name} ({reasons})"
            )
    for kohlebau in source.issuers:  # zusammengeführte Aussteller lösen auf den Nachfolger auf
        for former in kohlebau.former_ids:
            ctx.issuers.setdefault(former, ctx.issuers.get(kohlebau.id))


def document_kind_key(document: KohlebauDocument) -> str:
    """Schlüssel der Dokumentart in MoarCoal; leer für einen Beleg ohne Art."""
    if document.art is not None and document.art in KIND_BY_ART:
        return KIND_BY_ART[document.art]
    return KIND_BY_DOCUMENT_TYPE.get(document.document_type, "")


def _fill_label(
    ctx: Context, documents: Sequence[Document], document_type: str, report: Report
) -> None:
    """Trägt Kohlebaus Belegtyp als Bezeichnung nach, wo ein schon aufgenommenes Dokument keine
    hat; eine vorhandene (auch von Hand geänderte) bleibt."""
    if not document_type:
        return
    for existing in documents:
        if existing.label is not None:
            continue
        updated = existing.model_copy(update={"label": document_type})
        result = ctx.store.apply([Put(updated, entry_checksum(existing))])
        if isinstance(result, Rejected):
            report.count(
                "Bezeichnung abgewiesen", f"{existing.path}: {'; '.join(result.reasons.values())}"
            )
        else:
            report.count("Bezeichnung nachgetragen")


def import_documents(ctx: Context, source: Source, report: Report) -> None:
    """Nimmt jeden Beleg des Jahrs auf, dessen Datei (SHA-256) in einem Ablageort liegt, wie die
    Ablage es tut (`take_in`, mit Einlesen). Ohne passende Dokumentart: Beleg ohne Art."""
    kinds = {k.key: k for m in ctx.modules for k in m.document_kinds}
    files: dict[str, tuple[str, str]] = {}
    for site_file in all_site_files(ctx.store):  # nach Ablageort und Pfad, die erste gewinnt
        files.setdefault(site_file.sha256, (site_file.site, site_file.path))
    for document in source.documents:
        label = f"Beleg {document.id}"
        found = files.get(document.sha256)
        if found is None:
            report.count(
                "Beleg nicht in einem Ablageort",
                f"{label}: Datei liegt in keinem Ablageort, übersprungen.",
            )
            continue
        existing = documents_of_file(ctx.store.state().entries, ctx.user, document.sha256)
        if existing:
            report.count("Beleg schon aufgenommen")
            _fill_label(ctx, existing, document.document_type, report)
            continue
        issuer = ctx.issuers.get(document.issuer_id) if document.issuer_id else None
        site, path = found
        result = take_in(
            ctx.store,
            kinds,
            ctx.user,
            site,
            path,
            document_kind_key(document),
            source.year,
            values_on=lambda state: Values(
                ctx.modules, state, site_files=lambda: all_site_files(ctx.store)
            ),
            issuer=issuer,
            label=document.document_type or None,
        )
        if isinstance(result, IntakeRejected):
            report.count("Beleg abgewiesen", f"{label}: abgewiesen ({'; '.join(result.reasons)})")
        elif result.document.document_kind is None:
            report.count("Beleg aufgenommen (ohne Art)")
        else:
            report.count("Beleg aufgenommen (mit Art)")


PARTS: tuple[Part, ...] = (import_issuers, import_documents)


def run(
    kohlebau_root: Path,
    data_dir: Path,
    year: int,
    user: str,
    modules: Sequence[ModuleRegistration] = MODULES,
) -> Report:
    """Liest den Kohlebau-Ordner und übernimmt alle Teile; unlesbar: `SourceError`."""
    source = read_source(kohlebau_root, year)
    ctx = Context(open_module_store(data_dir, modules), modules, user)
    report = Report()
    for part in PARTS:
        part(ctx, source, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Übernimmt Aussteller und Belege aus Kohlebau.")
    parser.add_argument("kohlebau_root", type=Path, help="Quellordner von Kohlebau")
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Datenverzeichnis von MoarCoal"
    )
    parser.add_argument("--year", default=str(DEFAULT_YEAR), help="Steuerjahr der Belege")
    parser.add_argument("--user", default=DEFAULT_USER, help="Nutzer, dem die Belege gehören")
    args = parser.parse_args(argv)
    year = year_of(args.year, in_range=True)
    if year is None:
        parser.error("--year: Jahr als ganze Zahl im gültigen Bereich")
    try:
        report = run(args.kohlebau_root, args.data_dir, year, args.user)
    except SourceError as error:
        print(f"Abbruch: {error}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
