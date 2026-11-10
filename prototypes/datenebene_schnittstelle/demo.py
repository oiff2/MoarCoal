"""PROTOTYP – wegwerfen. Spielt die Skizze an zwei Fake-Modulen durch.

Start:  uv run --no-project python prototypes/datenebene_schnittstelle/demo.py
Alle Werte sind erfunden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import immobilie as imm
import steuerjahr as st
from datenebene import (
    Backing,
    Calculation,
    CatalogEntry,
    DocumentLocator,
    ExposedValue,
    MemoryStore,
    ModuleKey,
    ModuleRegistration,
    Money,
    NotYetComputable,
    Outcome,
    Period,
    Source,
    Unit,
    UserId,
    UserInputLocator,
    ValueCatalog,
    ValueDefinition,
    ValueKey,
    ValueRequest,
    Values,
    freeze,
)

ANNA = UserId("anna")
Y2025 = Period.year(2025)

# --- Ausgabe ------------------------------------------------------------------


def show(out: Outcome, indent: int = 0) -> None:
    p = " " * indent
    match out:
        case ExposedValue():
            subj = f" / {out.subject.display_name}" if out.subject else ""
            print(f"{p}■ {out.key}{subj} {out.time}: {out.amount}  [Belegstand: {out.backing}]")
            for s in out.workings:
                print(f"{p}    {s.kind:<17} {s.text}{': ' + str(s.amount) if s.amount is not None else ''}")
            for li in out.items:
                print(f"{p}    · {li.label}: {li.amount} | {li.locator} | {li.backing} | Quelle: {li.source.value if li.source else '–'}")
                if li.via:
                    show(li.via, indent + 8)
        case NotYetComputable():
            print(f"{p}□ {out.request.key} {out.request.subject_id or ''}: noch nicht berechenbar")
            for n in out.chain():
                print(f"{p}    ↳ {n.request.key} {n.request.subject_id or ''}: {n.reason}")


def findings(v: Values) -> None:
    for f in v.findings:
        print(f"  Befund [{f.severity}] {f.kind}: {f.text}")
    if not v.findings:
        print("  keine Befunde")


def header(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


# --- Testdaten (erfunden) -------------------------------------------------------


def seed(store: MemoryStore) -> None:
    store.write(
        ANNA,
        imm.KEY,
        imm.PropertyData(
            [
                imm.Property(
                    "obj-a",
                    "Musterweg 1",
                    [
                        imm.Loan(
                            "dl-1",
                            "Darlehen Musterbank 1",
                            [
                                imm.InterestEntry(
                                    2025,
                                    Money.eur("2400.00"),
                                    DocumentLocator("doc-jka-2025", Source.EXTRACTION, page=1, line=12),
                                    Backing.BACKED,
                                    "Zinsen lt. Jahreskontoauszug",
                                )
                            ],
                        ),
                    ],
                ),
                imm.Property(
                    "obj-b",
                    "Beispielstraße 7",
                    [
                        imm.Loan(
                            "dl-2",
                            "Darlehen Beispielbank",
                            [
                                imm.InterestEntry(
                                    2025,
                                    Money.eur("1100.00"),
                                    UserInputLocator(date(2026, 1, 15)),
                                    Backing.PENDING,
                                    "Zinsen geschätzt, Jahreskontoauszug kommt noch",
                                )
                            ],
                        ),
                    ],
                ),
                imm.Property("obj-c", "Gartenhaus Ohnedarlehen"),
            ]
        ),
    )


# --- Zyklus-Modul nur für die Demo --------------------------------------------


@dataclass
class Nothing:
    pass


A, B = ValueKey("loop.a"), ValueKey("loop.b")


def compute_a(c: Calculation[Nothing]) -> Money:
    return c.use(B).amount  # type: ignore[return-value]


def compute_b(c: Calculation[Nothing]) -> Money:
    return c.use(A).amount  # type: ignore[return-value]


LOOP = ModuleRegistration(
    ModuleKey("loop"),
    "Zyklus-Demo",
    Nothing,
    [
        ValueDefinition(CatalogEntry(A, "a", Unit.EUR, Period, False), compute_a),
        ValueDefinition(CatalogEntry(B, "b", Unit.EUR, Period, False), compute_b),
    ],
)


def main() -> None:
    catalog = ValueCatalog([imm.REGISTRATION, st.REGISTRATION, LOOP])  # type: ignore[list-item]
    store = MemoryStore()
    seed(store)

    header("1. Wertekatalog")
    for e in catalog.entries():
        print(f"  {e.key:<34} {e.unit.value:<3} {e.time_kind.__name__:<7} Bezugsobjekt: {e.needs_subject}  – {e.meaning}")

    header("2. Verbraucher fragt property.loan_interest 2025: ein Ergebnis je Bezugsobjekt")
    v = Values(catalog, store)
    for _, out in v.get(imm.LOAN_INTEREST, ANNA, Y2025).items():
        show(out, 2)
    findings(v)

    header("3. Steuerjahr: Ausgewiesener Wert mit Kette (Belegstand geerbt)")
    v = Values(catalog, store)
    show(v.get_one(ValueRequest(st.RENTAL_INTEREST_TOTAL, ANNA, Y2025)), 2)
    print("\n  Seite Anlage V:")
    for row in st.anlage_v_rows(v, ANNA, 2025):
        print(f"    {row[0]:<26} {row[1]:<28} {row[2]}")
    findings(v)

    header("4. Für 2024 fehlt jede Zinsangabe: „noch nicht berechenbar“ läuft die Kette hoch")
    v = Values(catalog, store)
    show(v.get_one(ValueRequest(st.RENTAL_INTEREST_TOTAL, ANNA, Period.year(2024))), 2)
    findings(v)

    header("5. Zyklus loop.a → loop.b → loop.a")
    v = Values(catalog, store)
    show(v.get_one(ValueRequest(A, ANNA, Y2025)), 2)
    findings(v)

    header("6. Immobilie für anna abgeschaltet (Regel offen, #24)")
    v = Values(catalog, store, disabled=frozenset({(ANNA, imm.KEY)}))
    show(v.get_one(ValueRequest(st.RENTAL_INTEREST_TOTAL, ANNA, Y2025)), 2)
    findings(v)

    header("7. Einfrieren")
    v = Values(catalog, store)
    snap = freeze(v, [ValueRequest(st.RENTAL_INTEREST_TOTAL, ANNA, Y2025)], "Abgabe ESt 2025", "doc-protokoll-2025")
    print(f"  Schnappschuss „{snap.occasion}“: {len(snap.values)} Wert(e), zu kopierende Dokumente: {snap.copied_documents}")
    v = Values(catalog, store)
    snap = freeze(v, [ValueRequest(st.RENTAL_INTEREST_TOTAL, ANNA, Period.year(2024))], "Abgabe ESt 2024", "doc-protokoll-2024")
    print(f"  Schnappschuss „{snap.occasion}“ trotz Lücke eingefroren:")
    for o in snap.values:
        show(o, 4)
    findings(v)

if __name__ == "__main__":
    main()
