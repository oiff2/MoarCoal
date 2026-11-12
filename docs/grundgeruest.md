# Spezifikation des Grundgerüsts

Architektur von MoarCoal, zusammengeführt aus der [Wayfinder-Karte: Grundgerüst MoarCoal](https://github.com/oiff2/MoarCoal/issues/1). Wer das Gerüst baut, braucht dieses Dokument, [`CONTEXT.md`](../CONTEXT.md) und die [ADRs](adr/). Begriffe sind dort definiert und werden hier nicht wiederholt. Einzelheiten und Begründungen stehen in den verlinkten Tickets.

Rangfolge bei Widerspruch: ADR vor diesem Dokument vor Ticket; ein späteres Ticket vor einem früheren. Was bei der Zusammenführung aufgelöst wurde, steht in [Abschnitt 10](#10-bei-der-zusammenführung-aufgelöst).

## Bauabschnitte

Die Entscheidungen unten gelten alle, gebaut werden sie aber nicht auf einmal. Zuerst kommt ein Durchstich, ein echter Ablauf von Anfang bis Ende. Von der Datenebene entsteht nur, was er braucht. Was der Bau widerlegt, wird hier nachgezogen.

**Abschnitt 1: Durchstich** ([#27](https://github.com/oiff2/MoarCoal/issues/27)): Nutzereingaben für Anlage N 2025, daraus Ausgewiesene Werte, Zuordnung zu Zeilen im Steuerjahr, Übertragungsprotokoll einlesen und abgleichen.

- Einträge und Adressen; Dokument mit Verweis auf den Ablageort; ein Nutzer, der Eigentümer steht trotzdem am Eintrag
- Contract mit Betrag oder noch nicht berechenbar, Einzelposten, Fundstelle, Belegstand, Rechenweg; Wertekatalog; `Values` mit Zwischenspeicher, Zykluserkennung und Prüfungen; `use` zwischen zwei Modulen
- Modulanmeldung, `ModuleState`, `evaluate(...)`
- Befunde und Befundliste, ohne Ausblenden
- `apply` mit `Put`/`Delete`, Prüfsummen, `.backup/`, temporäre Datei und Umbenennen; `schema`-Feld ab der ersten Datei
- Server mit Absicherung (Abschnitt 6), Testkern (Abschnitt 9)

**Abschnitt 2** ([#46](https://github.com/oiff2/MoarCoal/issues/46)), sobald der Durchstich steht: Auslesen mit Claude als Vorschlag mit Bestätigung (Abschnitt 7), am Beispiel des Bescheid-Abgleichs; Schnappschuss bei Abgabe, ohne Dokumentkopie; Erwarteter Beleg in einfacher Form; Ausblenden von Befunden; Eingang.

**Später, wenn es gebraucht wird**:

- Journal über mehrere Dateien ([ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md)): sobald Vorgänge regelmäßig mehrere Dateien schreiben
- Migration beim Start und Start-Archiv ([ADR 0004](adr/0004-migration-beim-start.md)): bei der ersten Schemaänderung
- Zusammenführen mit Alias (`Merge`)
- Neu auslesen mit Vorlagenfassung
- Dokumentkopie beim Einfrieren ([Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13))
- abgeleitete Sperrliste aus `Sensitive[str]` (Abschnitt 8)
- Abschalten von Modulen und „entfällt“: mit dem zweiten Nutzer
- Rhythmus und Ausnahmen am Erwarteten Beleg, Wiederfinden verschobener Dokumente, Abgleich zwischen Quellen
- Selbstbeendigung des Servers, Hellmodus

Die Befunde in [3.5](#35-befunde) sind die Zielliste; gebaut wird jeder mit dem Baustein, der ihn erzeugt.

## 1. Leitplanken

- Die **Datenebene** hält gespeicherte Daten und die Fachbausteine, die alle Module gleich brauchen. Themenlogik gehört ins **Modul**.
- Module kennen sich nicht. Sie verbinden sich nur über **Ausgewiesene Werte** und über **Adressen** von Einträgen.
- Verbraucher (v. a. Steuerjahr) greifen nur auf fertige Werte zurück und rechnen einfach weiter. Werte sind fachlich benannt, nicht nach Formularzeilen; die Zuordnung zur Zeile macht das Steuerjahr.
- Nie eine stille Null: Ein Wert hat einen Betrag, ist **noch nicht berechenbar** oder **entfällt**.
- Speicher nur über die Schnittstelle der Datenebene. Kein Modul liest oder schreibt Dateien direkt.
- Ein Autor, ein Repo: Module stehen in einer festen Liste im Code, keine Plugin-Laufzeit.
- Nichts geht automatisch nach außen. Jeder Netzzugriff (Claude, Vordrucke, Ortssuche, Kurse) wird vom Nutzer ausgelöst.
- Mehrere Nutzer, jeder mit getrennten Daten; jedes Dokument und jedes Bezugsobjekt gehört genau einem Nutzer.
- App-Sprache Deutsch, Code und Bezeichner Englisch; die Zuordnung steht nur in `CONTEXT.md`.

## 2. Überblick

```
 Browser (Windows)  ──HTTP 127.0.0.1──▶  Oberfläche (FastAPI + Jinja2 + htmx)
                                          │ Seiten der Module, Befundliste, Eingang,
                                          │ gemeinsamer Anzeigebaustein für Werte
                                          ▼
   Module (Immobilie, Steuerjahr, …)     Modulanmeldung: Schlüssel, Arten, Dokumentarten,
   Daten │ Fachkern │ Anbindung    ◀──── Auslese-Vorlagen, Befundarten, Seiten
                                          ▼
   Datenebene: Stand im Arbeitsspeicher, Rechenkontext, Wertekatalog, Befunde,
               Bausteine (Dokument, Aussteller, Vertrag, Notiz, Erwarteter Beleg,
               Vorschlag, Schnappschuss), Schreibweg, Aufrufbaustein für Claude
                                          ▼
   ~/MoarCoal/ (JSON)                    Ablageorte (nur lesen)
```

## 3. Datenebene

### 3.1 Einträge und Adressen

Gespeichertes mit eigener Adresse ist ein **Eintrag**; seine **Adresse** lautet `<Art>:<Kennung>`, z. B. `Property:7KQ2M9XA4T` ([ADR 0005](adr/0005-adressen-zufaellige-kennung.md), [Kennungen und Verweise](https://github.com/oiff2/MoarCoal/issues/20)).

- Kennung: zufällig beim Anlegen (z. B. 10 Zeichen Base32), global eindeutig, ändert sich nie.
- Art: Klassenname, über alle Module eindeutig (Testkern prüft). Wem eine Art gehört, steht in der Modulanmeldung.
- Jede Art liefert `display_name(id)` und `url(id)`; für Dokument, Aussteller, Vertrag, Erwarteter Beleg tut das die Datenebene. Unbekannte Art oder abgeschaltetes Modul: Adresse als Text ohne Link, kein Fehler.
- Andere Module sehen von einem fremden Eintrag nur Adresse, Anzeigenamen, Link und seine Ausgewiesenen Werte.
- Berechnetes ist kein Eintrag. Ein Ausgewiesener Wert wird über Schlüssel + Nutzer + Bezugsobjekt + Zeitbezug genannt, ein Einzelposten über Wert-Adresse + Fundstelle.
- Löschen wird nie verhindert. Notizen und Ausblendungen am Eintrag gehen mit, Zuordnungen auf ihn fallen weg, eine Fundstelle auf ein gelöschtes Dokument ergibt den Befund „Fundstelle fehlt“ (Fehler). Zusammenführen hinterlässt dauerhaft einen Alias.

### 3.2 Bausteine

| Baustein | Gehört | Kern | Ticket |
|---|---|---|---|
| Dokument | Nutzer | Aussteller, Datum, höchstens eine Dokumentart, ggf. Bezugszeitraum, Zuordnungen (Liste von Adressen), Datei am Ablageort (Ablageort + relativer Pfad + SHA-256) oder übernommen | [Bausteine](https://github.com/oiff2/MoarCoal/issues/4), [Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10), [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |
| Dokumentart | Code | angemeldet von Modulen, einige allgemeine von der Datenebene; legt fest, ob es einen Bezugszeitraum gibt | [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |
| Aussteller | gemeinsam | Anzeigename, weitere Namen, Art, Anschrift, Nummern (z. B. Steuernummer), Merkmal Privatperson; Zusammenführen mit Alias | [Bausteine](https://github.com/oiff2/MoarCoal/issues/4), [Sensible Werte](https://github.com/oiff2/MoarCoal/issues/14) |
| Vertrag | Nutzer | Aussteller, Vertragsnummer, Art, Laufzeit, Anzeigename; Bedeutung weiß das Modul | [Bausteine](https://github.com/oiff2/MoarCoal/issues/4) |
| Notiz | Nutzer | Text + Datum an einem Eintrag, einer Ausblendung oder einer Ausnahme, nie an Berechnetem | [Kennungen](https://github.com/oiff2/MoarCoal/issues/20) |
| Erwarteter Beleg | Nutzer | Aussteller, Dokumentart, Zuordnung, Rhythmus mit Beginn/Ende, Beschaffungsweg, Beschaffungshinweis (sensibel), Ausnahmen je Zeitraum mit Notiz | [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |
| Vorschlag | Nutzer | am Dokument: Felder mit Inhalt und Stelle im Dokument, Rohantwort, Fassung der Auslese-Vorlage, Bestätigungen und Korrekturen je Feld | [Claude als Baustein](https://github.com/oiff2/MoarCoal/issues/7), [Neu auslesen](https://github.com/oiff2/MoarCoal/issues/17) |
| Schnappschuss | Nutzer | Anlass, Datum, auslösendes Modul und Dokument, eingefrorene Werte | [Schnappschuss](https://github.com/oiff2/MoarCoal/issues/5), [ADR 0001](adr/0001-schnappschuss-statt-sperre.md) |
| Ausblendung | Nutzer | Befundart + Ziel-Adresse + Fingerabdruck + Pflicht-Notiz | [Befunde](https://github.com/oiff2/MoarCoal/issues/11) |
| Baustein „Nutzereingabe“ | eingebettet | Betrag, Datum, Beschreibung; jedes Modul bettet ihn in eigene Arten ein | [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |

Grundtypen:

- **Geldbetrag**: gespeichert in ganzen Cent, vorerst nur EUR. Zwischenschritte dürfen `Decimal` sein; gerundet wird im Modul, zu dem die Rundungsregel gehört, sichtbar im Rechenweg, und nur am Endergebnis, nie in Zwischenschritten (Werte, die in weitere Rechnungen eingehen, bleiben genau). Für die Felder einer Anlage rundet das Steuerjahr nach Einheit und Richtung des Felds ([#38](https://github.com/oiff2/MoarCoal/issues/38)).
- **Einheit** je Schlüssel aus fester Liste: EUR, Tage, km, m², Prozent.
- **Zeitbezug**: Zeitraum (`Period`, meist Kalenderjahr) oder Stichtag (`KeyDate`). Stichtagswerte werden nicht über Zeiträume summiert.

Was **nicht** zur Datenebene gehört: Konten und Buchungen, Immobilie, Darlehen, Fahrten, Steuerzeilen. Altjahre (2017–2024) sind normale Dokumente (Übertragungsprotokoll, Bescheid), aus denen das Steuerjahr belegte Werte macht.

### 3.3 Contract des Ausgewiesenen Werts

Quellen: [Contract](https://github.com/oiff2/MoarCoal/issues/2), [Zeitreihen und abgeleitete Werte](https://github.com/oiff2/MoarCoal/issues/16), [Ketten](https://github.com/oiff2/MoarCoal/issues/12), [Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19), [Abgeschaltetes Modul](https://github.com/oiff2/MoarCoal/issues/24).

- **Identität**: Schlüssel (`ValueKey`, im Wertekatalog mit Bedeutung, Einheit, Zeitbezugsart, Bezugsobjekt ja/nein) + Nutzer + Bezugsobjekt (falls nötig) + Zeitraum oder Stichtag.
- **Ergebnis** ist genau eines von: Betrag mit Einzelposten und Rechenweg; **noch nicht berechenbar** mit Grund (und Kette, wenn es an einem anderen Wert hängt); **entfällt** mit Grund.
- Der Wert ist das Ergebnis einer beliebigen Rechnung des Moduls, nicht zwingend eine Summe. Es gibt keine Rechenarten oder Merkmale wie „summierbar“ auf der Datenebene; Verhältniswerte sind normale Werte.
- **Einzelposten**: Zahl mit eigener Einheit und genau einer Fundstelle; die Quelle steht an der Fundstelle, nicht am Dokument. Der Belegstand ergibt sich aus der Art der Fundstelle, das Modul setzt ihn nie selbst:

  | Fundstelle | Belegstand | Quelle |
  |---|---|---|
  | Stelle in einem Dokument (Seite/Zeile) | belegt | ausgelesen oder eingelesen (steht an der Fundstelle) |
  | eDaten-Satz | belegt | eDaten-Abruf |
  | Erwarteter Beleg (für einen Zeitraum) | ausstehend | – |
  | Nutzereingabe (Adresse des Eintrags) | angenommen | Nutzereingabe |
  | anderer Ausgewiesener Wert | schwächster des Werts (geerbt) | keine eigene |

  Reihenfolge: ausstehend < angenommen < belegt. Der Belegstand eines Werts ist der schwächste seiner Einzelposten; ohne Einzelposten (z. B. ausdrücklich 0, begründet im Rechenweg) ist er belegt.
- **Ketten**: Ein Einzelposten darf sich auf einen anderen Wert stützen, beliebig tief. Die Posten des fremden Werts werden nicht kopiert, sondern beim Aufklappen gezeigt.
- **Fehlende Eingaben**: Entweder regelt die Rechnung sie ausdrücklich (`try_use`, Entscheidung im Rechenweg), oder der Wert ist noch nicht berechenbar, ebenso jeder Folgewert. Bei Angaben, die jedes Jahr wiederkehren können (z. B. Arbeitsmittel), heißt „nichts erfasst“ ausdrücklich 0, begründet im Rechenweg; standen im Vorjahr welche, gibt es zusätzlich einen Hinweis-Befund (vergessen?). Der Abgleich wertet ein im Übertragungsprotokoll fehlendes Feld als 0, denn ELSTER überträgt leere Felder nicht. Ein Zyklus macht alle beteiligten Werte noch nicht berechenbar und ergibt einen Fehler-Befund mit der Kette.
- **Entfällt**: Werte abgeschalteter Module liefert die Datenebene als „entfällt“; eine Modul-Rechnung nur als ausdrückliche Entscheidung. Geht ein entfallender Wert in eine Rechnung ein, fehlt dort sein Einzelposten, der Rechenweg nennt den Grund, die Rechnung läuft weiter.
- **Dieselbe Fundstelle** darf in einem Wert nur einmal vorkommen, auch über Ketten; sonst Fehler-Befund, der Wert wird trotzdem berechnet.
- Werte werden **auf Anfrage berechnet** und nie gespeichert, außer im Schnappschuss. Eine Zeitreihe ist eine geordnete Folge von Werten, kein eigener Typ. Vergleiche über Jahre zeigen immer den aktuellen Stand.
- Ein unbekannter Schlüssel ist ein Programmfehler, keine Null.

### 3.4 Rechenkontext (Skizze)

Die Skizze auf Branch [`prototype/datenebene-schnittstelle`](https://github.com/oiff2/MoarCoal/tree/prototype/datenebene-schnittstelle) bestätigt die Form; dieser Abschnitt hält den Stand nach allen späteren Tickets fest. Signaturen sind Richtung, nicht Vorgabe.

```python
@dataclass(frozen=True)
class ValueDefinition:
    entry: CatalogEntry                     # Schlüssel, Bedeutung, Einheit, Zeitbezugsart, Bezugsobjekt ja/nein
    compute: Callable[[Calculation], Amount]
    subjects: Callable[[ModuleState, TimeRef], list[Subject]] | None   # nur bei Werten mit Bezugsobjekt

class ModuleState:                          # Stand, eingegrenzt auf ein Modul und einen Nutzer, nur lesen
    def all[E](self, kind: type[E]) -> list[E]: ...           # nur eigene Arten
    def get(self, address: EntryAddress) -> Entry | None: ... # fremde Art → Programmfehler
    def documents(self, address: EntryAddress) -> list[Document]: ...   # mit Zuordnung auf den Eintrag
    # ebenso Notizen, Erwartete Belege, Verträge des Nutzers, Aussteller (gemeinsam)

class Calculation:                          # eine je Rechnung, ohne Speicherzugang
    own: ModuleState
    subject: Subject | None
    time: TimeRef                           # Period | KeyDate
    def item(self, label: str, amount: Amount, locator: Locator) -> LineItem: ...   # Belegstand aus locator
    def use(self, key: ValueKey, **kw) -> LineItem | None: ...      # fehlt → noch nicht berechenbar; entfällt → None + Rechenweg
    def try_use(self, key: ValueKey, **kw) -> LineItem | Missing: ...  # Fehlen selbst regeln
    def subjects_of(self, key: ValueKey, time: TimeRef | None = None) -> list[Subject]: ...
    def step(self, text: str, amount: Amount) -> Amount: ...
    def decide(self, text: str) -> None: ...
    def not_yet(self, reason: str) -> NoReturn: ...
    def not_applicable(self, reason: str) -> NoReturn: ...

class Values:                               # eine je HTTP-Anfrage, auf dem festgehaltenen Stand
    def get(self, key, user, time, subject=None) -> ExposedValue | NotYetComputable | NotApplicable: ...
    def all(self, key, user, time) -> list[...]: ...   # ein Ergebnis je aufgezähltem Bezugsobjekt
```

- Die Datenebene ruft `compute` mit dem eingegrenzten Stand des Moduls auf; das Modul rechnet ohne Speicherzugang. Ein Modul baut kein eigenes Datenobjekt; Sortieren nach Jahr oder Bezugsobjekt macht der Fachkern je Anfrage. Dieselbe `ModuleState` bekommen Befundquelle und Seiten des Moduls. Von fremden Einträgen sieht ein Modul nur Anzeigenamen und Link (über die Adresse) und ihre Ausgewiesenen Werte ([Interface der Datenebene](https://github.com/oiff2/MoarCoal/issues/26)).
- `Values` hält einen Zwischenspeicher je Anfrage, erkennt Zyklen über den Stapel laufender Anfragen und prüft Einheit, Zeitbezugsart, Bezugsobjekt nötig/nicht und doppelte Fundstellen. Was dabei auffällt, wird Befund.
- Bezugsobjekte zählt das Modul auf, dem der Schlüssel gehört, abhängig vom Zeitbezug. Filter wie „vermietet“ sind ein eigener fertiger Wert mit passender Aufzählung, nie ein Filter im Verbraucher.
- Bei abgeschaltetem Modul fragt die Datenebene das Modul gar nicht: Aufzählung leer, Werte ohne Bezugsobjekt „entfällt“.
- **Stand des Baus (Durchstich, [#31](https://github.com/oiff2/MoarCoal/issues/31)):** Code in `src/moarcoal/values/` (`model`, `catalog`, `calculation`, `engine`; das Paket führt absichtlich keine Re-Exporte, weil `registration` den Katalog importiert und `engine` die Anmeldung). Die Rechnung liefert einen `Amount` (Zahl mit Einheit); `Values` prüft ihn gegen die Einheit im Katalog, ebenso Zeitbezugsart und Bezugsobjekt. `Values.all` zählt über `ValueDefinition.subjects` auf. Gebaut ist noch nicht: Stichtagswerte in Modulen. Doppelte Fundstellen prüft `Values` seit [#40](https://github.com/oiff2/MoarCoal/issues/40) (Befundart `duplicate_locator`, Fehler, Ziel der Wert): nach der Rechnung werden die Fundstellen der Einzelposten samt der über `ValueLocator` aufgeklappten Posten fremder Werte gezählt; kommt eine zweimal vor (auch dieselbe Nutzereingabe über zwei verschiedene Werte einer Kette), entsteht ein Befund je Wert, der Wert bleibt berechnet. Die Anmeldung trägt `values` und `entry_url` (Link einer Adresse zur Seite des Eintrags); der Anzeigebaustein ist das Makro `templates/_value.html` mit `<details>`, ohne Skript. Schlüssel von Arbeit: `work.workdays` und `work.distance_km` (je erster Tätigkeitsstätte als Bezugsobjekt), `work.equipment` (Summe je Jahr).
- **Stand des Baus (Durchstich, [#32](https://github.com/oiff2/MoarCoal/issues/32)):** `use`, `try_use` und `subjects_of` laufen über dieselbe `Values` (Schnittstelle `ValueSource`). `use` macht aus dem fremden Wert einen Einzelposten mit der Fundstelle `ValueLocator` (Code im Modul `values.model`): Betrag und schwächster Belegstand werden geerbt, die Posten des fremden Werts liegen nicht als Kopie im Einzelposten, sondern hängen am `ValueLocator` und werden beim Aufklappen gezeigt. `NotYetComputable` trägt eine `chain` (zuerst der verwendete Wert, zuletzt der, an dem es liegt). `Values` erkennt Zyklen über den Stapel laufender Anfragen: alle Beteiligten sind noch nicht berechenbar, und `Values.findings` bekommt einen Befund der Art `cycle` (Fehler) mit der Kette (`Finding`, `values/findings.py`; die Befundliste ist noch nicht gebaut). Das Steuerjahr führt seine Felder der Anlage N je Steuerjahr in `modules/tax_year/anlage_n.py` (`FORMS`, bisher nur 2025; für ein Jahr ohne Katalog sind die Felder noch nicht berechenbar) und ordnet ihnen über `use` die Werte von Arbeit zu. Das Feld (`FormField` in `modules/tax_year/fields.py`: Schlüssel, E-Kennung oder leer, Nr. im Vordruck, Bezeichnung, Einheit, Rundung, Richtung) rundet, zeigt seinen Wert an, liest den Inhalt seiner Protokollfelder und nennt eine Abweichung; die Rechnung hält den Rundungsschritt im Rechenweg fest. Die Bezeichnungen im Wertekatalog tragen keine Jahreszahl; Schlüssel `tax_year.n_workplace_days`, `tax_year.n_workplace_distance`, `tax_year.n_equipment`. Ein Feld zeigt die erfassten Angaben, nicht die Entfernungspauschale. Mehrere erste Tätigkeitsstätten in einem Jahr machen die beiden Felder noch nicht berechenbar, bis feststeht, wie sie den Einträgen der Tabelle zugeordnet werden. Arbeitsmittel: Summe in Zeile 56, E-Kennung `E0204403` (Seite „10 - Aufwendungen für Arbeitsmittel“ in Mein ELSTER, gelesen mit `tools/elster_page_fields.py`); ein im Protokoll fehlendes Feld gilt als 0. Seite: `/steuerjahr/anlage-n/2025`.
- **Stand des Baus (Durchstich, [#34](https://github.com/oiff2/MoarCoal/issues/34)):** Die Modulanmeldung trägt `finding_kinds` (`FindingKind`) und `findings` (eigener Stand, Werte, Jahr -> Befunde). `Values.finding_list(user, year)` rechnet alle Zeitraumwerte des Jahrs (Stichtagswerte noch nicht), sammelt Zyklus-Befunde und die der Module, Fehler zuerst; die Seite `/befunde?year=…` zeigt sie (Jahr vorerst Vorgabe 2025), die Seite der Anlage N zeigt dieselben. `Finding.href` führt zur Stelle der Prüfung. Abgleich in `modules/tax_year/comparison.py` gegen das zuletzt aufgenommene Protokoll des Jahrs (`Document.taken_in_at`): Abweichung, Feld fehlt, mehrdeutig (Tage/km mehrfach) je Warnung; Feld ohne E-Kennung ein Hinweis; kein Abgleich bei Werten, die nicht berechenbar sind oder entfallen, und ohne Protokoll. Exakt und ohne Toleranz gegen den gerundeten Feldwert (das Feld rundet nach `Rounding` und `Direction`, die Rechnung des Felds hält den Rundungsschritt im Rechenweg fest; Recherche in [`recherche-runden-anlage-n.md`](recherche-runden-anlage-n.md)); bei reiner Rundungsabweichung nennt der Text Differenz und Richtung; EUR-Zeilen mit gleicher E-Kennung summiert. Ausblenden und Fingerabdruck fehlen noch.
- Abweichung von der Skizze: `item` nimmt keinen Belegstand mehr entgegen ([Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21)); statt `Store.read`/`Store.write` je Modul mit Datenobjekt `D` gibt es den eingegrenzten Stand zum Lesen und Vorgänge aus Änderungen an Einträgen zum Schreiben ([ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md), [Interface der Datenebene](https://github.com/oiff2/MoarCoal/issues/26)).

**Modul-Tests** laufen über dieselbe Implementierung von `Values` wie der Betrieb, nie über ein nachgebautes `Calculation`:

```python
values = evaluate(
    modules=[property_module],
    entries=[Loan(...), Property(...)],                      # daraus wird ein Stand, ohne Dateien
    foreign={("bank.interest", subject, Period.year(2025)): fixed(Money.eur("100,00"), backing=Backing.PENDING)},
)
values.get("property.loan_interest", user, Period.year(2025), subject)
```

- `foreign` ersetzt fremde Module durch fest vorgegebene Ergebnisse (Betrag, noch nicht berechenbar, entfällt). Ein Schlüssel, der weder angemeldet noch vorgegeben ist, ist ein Programmfehler wie im Betrieb.
- Mehrere echte Module zusammen: alle in `modules`, `foreign` leer. Befundquellen gehen den gleichen Weg (`findings(...)`).
- **Stand des Baus ([#43](https://github.com/oiff2/MoarCoal/issues/43)):** gebaut in `values/testing.py` (`evaluate`, `fixed`, `not_yet`, `not_applicable`); `Values` nimmt `foreign` an und schaut dort vor dem Wertekatalog nach. Bezugsobjekte eines vorgegebenen Schlüssels ergeben sich aus den Schlüsseln in `foreign` für den Zeitbezug. Ein Schlüssel, der angemeldet und vorgegeben ist, und eine fehlende Vorgabe für den angefragten Zeitbezug sind `ContractViolation`. `fixed` trägt einen Einzelposten mit eigener Fundstelle (Belegstand wählbar, sonst angenommen). Das Steuerjahr baut ein Test mit eigenem Katalog über `tax_year.registration(forms=...)`; die Tests des Steuerjahrs nutzen das echte Modul Arbeit nur noch für die Seiten, den ganzen Ablauf und den Fall „kein Arbeitsmittel, Vorjahr schon“.

### 3.5 Befunde

Quelle: [Befunde](https://github.com/oiff2/MoarCoal/issues/11), [Kennungen](https://github.com/oiff2/MoarCoal/issues/20).

- Erzeuger: die Datenebene für ihre Bausteine, Module für Fachliches (über Befundarten in der Modulanmeldung). Was die Datenebene meldet, meldet kein Modul noch einmal. Module dürfen dafür fremde Ausgewiesene Werte lesen.
- Berechnet auf Anfrage, nie gespeichert. Die Befundliste rechnet alle Schlüssel des Wertekatalogs für das globale Jahr (Zeitraumwerte fürs Kalenderjahr, Stichtagswerte zum 31.12.) und sammelt die Befundquellen. Befunde anderer Jahre zeigt die Seite, die den Wert anfragt.
- Ein Befund hat Befundart (angemeldeter Schlüssel), Schweregrad (Hinweis, Warnung, Fehler), Ziel-Adresse (Eintrag, Wert oder Einzelposten) und einen Fingerabdruck des Stands vom Erzeuger.
- Ausblenden mit Pflicht-Notiz, gespeichert je Nutzer; geänderter Fingerabdruck bringt den Befund zurück. Ausgeblendete Fehler werden weiter gezählt.

Befunde der Datenebene (Stand der Karte):

| Befund | Schweregrad | Ticket |
|---|---|---|
| Erwarteter Beleg für einen Zeitraum ausstehend | Hinweis | [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |
| Erwarteter Beleg: mehrere passende Dokumente; mögliche Dublette | Hinweis | ebd. |
| Dokument ohne Dokumentart; fehlender Bezugszeitraum | Hinweis | ebd. |
| Unbestätigter Vorschlag | Hinweis | [Claude als Baustein](https://github.com/oiff2/MoarCoal/issues/7) |
| Auslese-Vorlage neuer als Vorschlag (je Dokumentart) | Hinweis | [Neu auslesen](https://github.com/oiff2/MoarCoal/issues/17) |
| Neu ausgelesener Wert weicht vom bestätigten ab | Warnung | ebd. |
| Einlesen hat einen Wert geändert | Hinweis | ebd. |
| Dateien im Eingang | Hinweis | [Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10) |
| Dokument fehlt am Ablageort / Inhalt geändert / verschoben | Hinweis | [Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10), [Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13) |
| Fundstelle fehlt (Dokument gelöscht) | Fehler | [Kennungen](https://github.com/oiff2/MoarCoal/issues/20) |
| Zyklus; noch nicht berechenbar; doppelte Fundstelle | Fehler | [Ketten](https://github.com/oiff2/MoarCoal/issues/12), [Abgleich](https://github.com/oiff2/MoarCoal/issues/18) |
| Abweichung zum Schnappschuss | vom Modul gewählt | [Schnappschuss](https://github.com/oiff2/MoarCoal/issues/5) |
| Eingefrorener Wert war noch nicht berechenbar | Fehler | [Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19) |
| Modul abgeschaltet, hat aber Einträge | Hinweis | [Abgeschaltetes Modul](https://github.com/oiff2/MoarCoal/issues/24) |
| Entfallener Schlüssel außerhalb von Schnappschüssen verwendet | Warnung | [Schema-Evolution](https://github.com/oiff2/MoarCoal/issues/15) |
| Claude-Aufruf meldet Werkzeuge oder MCP-Server | Fehler | [ADR 0007](adr/0007-absicherung-server-und-claude-aufruf.md) |
| Abgeleitete Sperrliste konnte nicht geschrieben werden | Warnung | [ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md) |

### 3.6 Aufnehmen, auslesen, einlesen

Quellen: [Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10), [Claude als Baustein](https://github.com/oiff2/MoarCoal/issues/7), [Neu auslesen](https://github.com/oiff2/MoarCoal/issues/17), [Abgleich](https://github.com/oiff2/MoarCoal/issues/18).

1. **Eingang**: Dateien in Ablageorten, die weder aufgenommen noch ausgeblendet sind (erkannt über SHA-256). Nichts wird von selbst übernommen. Ausblenden gilt für alle Nutzer.
2. **Aufnehmen** macht ein Dokument (Nutzer, Dokumentart, Zuordnungen). Danach je Dokumentart einlesen, auslesen oder beides.
3. **Auslesen** (nur von Hand, je Dokument oder je Dokumentart): Claude füllt die Auslese-Vorlage (mit Fassungsnummer), das Ergebnis ist ein Vorschlag am Dokument. Der Nutzer bestätigt je Feld oder alle; erst dann übernimmt das Modul die Felder in seine Daten. Korrekturen behalten Fundstelle und Quelle.
4. **Neu auslesen** legt einen neuen Vorschlag neben den alten. Gleicher Wert bleibt bestätigt, abweichender ergibt eine Warnung, nie wird überschrieben. Eine wiederholte Fehllesung eines korrigierten Felds bleibt ohne Befund.
5. **Einlesen** ist exakt, gilt ohne Bestätigung und läuft beim Start neu, wenn sich das Einlesen geändert hat; ein geänderter Wert ersetzt den alten mit Hinweis-Befund. Wer einen eingelesenen Wert für falsch hält, legt eine Nutzereingabe mit Notiz an.
6. **Dieselbe Tatsache aus zwei Quellen** regelt das Modul: Merkmale je Eintragsart, an denen derselbe Eintrag erkannt wird („gehört zu bestehendem Eintrag“ in der Bestätigungsansicht, nie still zusammenführen), maßgebliches Dokument und ggf. Ersatz je Eintragsart. Ein Einzelposten hat genau eine Fundstelle; weitere Dokumente hängen nur am Eintrag.
7. Ein vorhandenes, aber unbestätigtes Dokument erfüllt seinen Erwarteten Beleg; der Einzelposten bleibt ausstehend bis zur Bestätigung.

### 3.7 Schnappschuss

Quellen: [Schnappschuss](https://github.com/oiff2/MoarCoal/issues/5), [Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13), [ADR 0001](adr/0001-schnappschuss-statt-sperre.md), [ADR 0003](adr/0003-belege-verweisen-statt-kopieren.md).

- Ausgelöst von einem Modul zu einem Anlass (erst: Abgabe, belegt durch das Übertragungsprotokoll). Der Bescheid erzeugt keinen. Berichtigungen ergeben einen neuen Schnappschuss daneben. Altjahre vor 2025 haben keine.
- Eingefroren wird die **ganze Kette**: jeder Wert mit Einzelposten, Belegstand, Rechenweg und Fundstellen, auch Werte, die noch nicht berechenbar waren oder entfallen (mit Grund). Einfrieren verhindert nichts.
- Im selben Vorgang werden alle Dokumente aus Fundstellen der Kette und das auslösende Dokument nach `users/<id>/documents/<sha256-prefix>/` kopiert (dedupliziert). Diese Kopien werden nie gelöscht, solange ein Schnappschuss auf sie verweist.
- Eingaben bleiben änderbar. Der Vergleich Schnappschuss ↔ aktueller Stand liefert Abweichungen je Stufe der Kette; ob daraus ein Befund wird, entscheidet das auslösende Modul.
- Format klein und stabil (Schlüssel, Beträge, Einzelposten, Fundstellen als Klartext), wird nicht migriert.

## 4. Modulebene

Quellen: [Wie ein Modul sich einhängt](https://github.com/oiff2/MoarCoal/issues/6), [Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19), [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21), [Abgeschaltetes Modul](https://github.com/oiff2/MoarCoal/issues/24).

**Modulanmeldung** (`ModuleRegistration`), ein Eintrag je Modul in einer festen Liste im Code:

| Inhalt | Wozu |
|---|---|
| Modulschlüssel, Bereichsname, Navigationseintrag, Seiten (Router) | Oberfläche zeichnet nur Angemeldetes; Reihenfolge der Bereiche in einer Liste in der App |
| Datenmodelle (Pydantic) mit Schemaversion und Migrationen; je Art eine reine Funktion Eintrag → relativer Pfad der Datei | Laden, Prüfen, Migrieren und Ablegen durch die Datenebene |
| Arten von Einträgen mit `display_name`/`url` | Adressen auflösen |
| Je Schlüssel eine `ValueDefinition` | Wertekatalog und Rechnen |
| Dokumentarten (mit/ohne Bezugszeitraum), Auslese-Vorlagen mit Fassung, Einlese-Regeln | Aufnehmen, auslesen, einlesen |
| Je Eintragsart: Erkennungsmerkmale, maßgebliches Dokument und Ersatz (wo nötig) | Abgleich zwischen Quellen |
| Befundarten und eine Funktion, die Befunde liefert (optional) | Befundliste |

Weitere Regeln:

- Je Modul drei Schichten: **Daten** (Modelle, von der Datenebene geladen), **Fachkern** (reine Funktionen, einzeln testbar), **Anbindung** (übersetzt in Einzelposten und Rechenweg; ruft in Seiten `apply` auf).
- Auch Schreiblogik ist rein: Eine Funktion des Moduls bekommt den eingegrenzten Stand und liefert eine Liste von Änderungen (z. B. Vorschlag bestätigen); nur die Anbindung übergibt sie an `apply` (siehe [5.2](#52-lesen-und-schreiben)).
- Module speichern nur Fachdaten. Einzelposten entstehen immer erst beim Rechnen; was von Hand eingegeben werden kann, ist eine eigene Art des Moduls mit dem eingebetteten Baustein Nutzereingabe.
- Fremde Werte zeigt ein Modul nur über den gemeinsamen Anzeigebaustein (Betrag, aufklappbare Einzelposten und Rechenweg, Link zum Ursprungsmodul), nie mit Seitenteilen anderer Module.
- Übergreifende Dashboards sind vorläufig eigene Verbraucher-Module.
- **Abschalten** je Nutzer heißt „betrifft mich nicht“: Navigation, Befunde und Aufzählung fallen weg, Werte entfallen, Daten bleiben. Beim Abschalten fragt die Oberfläche nach, wenn das Modul Einträge hat.
- Ein Modul schlägt Erwartete Belege nur per Hinweis-Befund vor; anlegen tut sie der Nutzer.

## 5. Speicher

Quellen: [Speicher](https://github.com/oiff2/MoarCoal/issues/3), [Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10), [Schema-Evolution](https://github.com/oiff2/MoarCoal/issues/15), [Schreibweg](https://github.com/oiff2/MoarCoal/issues/22), [ADR 0003](adr/0003-belege-verweisen-statt-kopieren.md), [ADR 0004](adr/0004-migration-beim-start.md), [ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md).

### 5.1 Datenverzeichnis

```
~/MoarCoal/                         lokal in WSL, kein Sync-Ordner
├── users/<id>/
│   ├── <modul>/…                   Gliederung nach Jahr/Bezugsobjekt legt das Modul je Art fest (Eintrag → Pfad)
│   ├── <baustein>/…                Bausteine der Datenebene je Nutzer (Dokumente, Verträge, …)
│   └── documents/<sha256-prefix>/  übernommene Dateien: Uploads und Kopien beim Einfrieren
├── common/
│   ├── issuers…                    Aussteller-Katalog
│   ├── sites.json                  benannte Ablageorte, in der Oberfläche bearbeitbar
│   └── derived-denylist.txt        aus sensiblen Feldern, liest tools/privacy_guard.py
├── config/                         App-Einstellungen (u. a. Port)
├── .backup/                        letzte 20 Fassungen je Datei, gekürzt beim Start
└── .cache/                         löschbar, nicht gesichert (späterer SQLite-Index, Vorschaubilder)
```

- Ordner- und Dateinamen im Datenverzeichnis sind englisch wie der Code (`users/`, `common/`, Module unter ihrem Code-Namen, z. B. `tax_year/`); die Oberfläche bleibt deutsch.
- Nur JSON, stabil formatiert: Schlüssel sortiert, eingerückt, UTF-8, Zeilenende am Dateiende. Jede Datei trägt `"schema": "<modul>/<n>"`.
- Dokumente an Ablageorten werden verwiesen (Ablageort + relativer Pfad + SHA-256), nie kopiert, außer beim Einfrieren. MoarCoal liest dort nur.
- Fehlt eine Datei, wird der Ablageort nach demselben SHA-256 durchsucht. Gelesen wird beim Zugriff, persistiert nur über die Schnittstelle (siehe [Abschnitt 10](#10-bei-der-zusammenführung-aufgelöst)).
- Ein SQLite-Index kann später hinter der Schnittstelle ergänzt werden; er ist nie eigene Wahrheit.

### 5.2 Lesen und Schreiben

- Ein Server-Prozess. Beim Start lädt die Datenebene alles als unveränderlichen Stand und merkt sich je Datei die Prüfsumme. Jede Anfrage hält ihren Stand fest und liest ohne Sperre.
- Geschrieben wird nur in einem **Vorgang** hinter einer einzigen Schreibsperre: prüfen (Pydantic) → Prüfsummen vergleichen (Datei: Handänderung abweisen; Eintrag: veralteten Tab mit „inzwischen geändert“ abweisen) → `.backup/` → temporäre Dateien mit `fsync` → Journal → umbenennen → Journal löschen → Stand tauschen. Danach ggf. abgeleitete Sperrliste neu schreiben.
- Schreib-Endpunkte sind normale `def` im Threadpool. GET schreibt nie.

Interface ([Interface der Datenebene](https://github.com/oiff2/MoarCoal/issues/26)):

```python
store = open_store(root, sites)             # Datenverzeichnis und Ablageorte werden übergeben
state = store.state()                       # Stand, unveränderlich; einmal je Anfrage festhalten
result = store.apply([                      # ein Vorgang
    Put(entry, expected=checksum),          # anlegen (expected=None) oder ersetzen
    Delete(address, expected=checksum),
    Merge(source, into),
])                                          # -> Applied(changes) | Rejected(reasons je Adresse)
```

- Einheit des Schreibens ist der **Eintrag**, nicht die Datei und nicht das ganze Modul. In welche Datei ein Eintrag gehört, sagt die Funktion Eintrag → Pfad aus der Modulanmeldung; Module fassen Dateien nie an.
- Änderungen sind einfache Werte. Kennungen neuer Einträge entstehen beim Bauen der Änderung, nicht in `apply`, damit Verweise in derselben Liste stehen können.
- **Folgen rechnet `apply` aus**: Löschen nimmt Notizen und Ausblendungen am Eintrag mit und entfernt Zuordnungen auf ihn; Zusammenführen legt den Alias an und hängt Verweise in Bausteinen der Datenebene um; ein neuer Schnappschuss kopiert die Dokumente seiner Kette; ein Upload übernimmt die Datei. `Applied` nennt alle ausgeführten Änderungen samt Folgen, fürs Protokoll. Eine Vorschau der Folgen gibt es vorerst nicht; die Funktion, die sie ausrechnet, ist rein und kann später ausgewiesen werden.
- Abweisungen (Prüfung, Handänderung an der Datei, veralteter Tab) kommen als `Rejected` zurück, nicht als Ausnahme.
- Ein Vorgang ist nicht an einen Nutzer gebunden; jeder Eintrag trägt seinen Eigentümer, Gemeinsames (Aussteller, Ausblendungen im Eingang) geht denselben Weg.
- Keine Seam zum Dateisystem: Tests nutzen echte Wegwerfverzeichnisse. Wiederherstellung über das Journal wird geprüft, indem der Test den Zustand nach einem Absturz (temporäre Dateien mit oder ohne Journal) anlegt und startet; ein einzelner Test lässt intern `os.replace` scheitern.

**Stand des Baus (Durchstich, [#29](https://github.com/oiff2/MoarCoal/issues/29)):** Das Journal ist noch nicht gebaut. Scheitert das Umbenennen mittendrin, stellt `apply` die schon ersetzten Dateien wieder her; ein Absturz mitten im Umbenennen ist nicht abgedeckt. Eine Datei enthält `{"schema", "entries": {"<Adresse>": {…}}}`; eine Datei, die leer würde, entfällt. Dateiformat und Pfad je Eintragsart stehen in `EntryKind` (`schema`, `path`), das die Modulanmeldung in `kinds` liefert ([#30](https://github.com/oiff2/MoarCoal/issues/30)); `open_store` bekommt diese Liste. Code: `src/moarcoal/storage/`.

**Stand des Baus (Durchstich, [#30](https://github.com/oiff2/MoarCoal/issues/30)):** `ModuleRegistration` (`src/moarcoal/registration.py`) trägt bisher Schlüssel, Bereichsname, Navigationseintrag, Router und `kinds`; die feste Liste steht in `src/moarcoal/modules/__init__.py`. `ModuleState` ist auf die Arten des Moduls und einen Nutzer eingegrenzt; eine fremde Art ist ein Programmfehler (`ForeignKindError`). Das Modul Arbeit (`work`) hat die Arten `FirstWorkplace` und `WorkEquipment` mit dem eingebetteten `UserInput`, Dateien unter `users/<id>/work/<jahr>.json`. Die App bekommt das Datenverzeichnis über `create_app(port, data_dir)`; `__main__` nimmt `MOARCOAL_DATA_DIR` oder `default_data_dir()`. Der Nutzer ist im Durchstich fest (`DEFAULT_USER`). Formulare sind einfache POSTs mit 303-Weiterleitung, ohne htmx.

**Stand des Baus (Durchstich, [#33](https://github.com/oiff2/MoarCoal/issues/33)):** `Document` (`storage/documents.py`, Datei `users/<id>/documents.json`, Format `datenebene/1`) trägt Ablageort, relativen Pfad, SHA-256, Dokumentart und Bezugszeitraum (Beginn/Ende); `open_store` nimmt die Arten der Datenebene immer dazu. Ablageorte stehen in `common/sites.json` (`{"schema": "ablageorte/1", "sites": {Name: absoluter Ordner}}`, ein Windows-Pfad wie `G:\Steuer` wird zu `/mnt/g/Steuer`, vorerst von Hand gepflegt, keine Einträge) oder werden `open_store(root, kinds, sites)` übergeben; `Store.read_site_file` liest nur, weist `..`, absolute Pfade und Links aus dem Ablageort hinaus ab. Eine Dokumentart (`DocumentKind`, `documents.py`) steht in der Modulanmeldung (`document_kinds`) mit Einlese-Regel `read_in(Document, bytes) -> Einträge`; `take_in` liest die Datei, weist eine schon aufgenommene (gleicher SHA-256, gleicher Nutzer) ab und schreibt Dokument und eingelesene Einträge in einem Vorgang. Das Modul Steuerjahr (`tax_year`) liest das Übertragungsprotokoll ein (Aufbau nach dem Vorgängerprojekt, ADR 0012 dort): Kopf aus HTML-Kommentaren (`Belegart: E10`, `Belegversion`, `Veranlagungsjahr`, oft leer) und dem Text „Eingang auf Server“; jedes Feld ist eine Tabellenzeile mit einem `<span data-name="id-<Anlage>-…-E<7 Ziffern>_usb<Index>">` in der Zelle des Inhalts. Je Feld mit E-Kennung (letztes Pfadsegment) steht im Eintrag `ProtocolReading` (`users/<id>/tax_year/<jahr>.json`) eine `ProtocolLine`: E-Kennung, Anlage, Nummer im Vordruck (erste Zelle, 1 bis 3 Ziffern), Bezeichnung (Zelle vor dem Inhalt), Inhalt als Rohtext, Index der Wiederholgruppe und als Fundstelle der volle `data-name`. Dieselbe E-Kennung kann mehrfach vorkommen; nichts wird summiert oder umgerechnet (das ist der Abgleich, #34). Felder ohne E-Kennung entfallen. Gibt der Kopf ein Jahr an (Veranlagungsjahr, sonst eine vierstellige Belegversion) und widerspricht es dem eingetragenen Steuerjahr, weist das Aufnehmen ab. Neu Einlesen beim Start und der Hinweis-Befund „Einlesen hat einen Wert geändert“ fehlen noch (`reader_version` steht schon am Eintrag).

### 5.3 Start-Reihenfolge

1. Journal zu Ende führen bzw. Temp-Reste verwerfen
2. Archiv des ganzen Datenverzeichnisses sichern
3. Migration aller Dateien auf das aktuelle Format (Fehler → kein Start, Datei wird genannt)
4. Laden mit Prüfsummen
5. Neu einlesen, wo sich das Einlesen geändert hat
6. Sperrliste schreiben
7. `.backup/` kürzen
8. Server lauscht; Browser öffnet sich

Der Code kennt nur das aktuelle Format. Umbenannte Schlüssel und Arten schreibt die Migration in Arbeitsdaten um; Aliasse (`früher`) gibt es nur für Schnappschüsse, der Testkern meldet verwaiste. Entfallene Schlüssel werden markiert statt gelöscht.

## 6. Oberfläche und Server

Quellen: [Technikentscheidung](https://github.com/oiff2/MoarCoal/issues/8), [ADR 0002](adr/0002-technikstack.md), [ADR 0007](adr/0007-absicherung-server-und-claude-aufruf.md).

- Python mit uv, strikte Typprüfung. FastAPI + Jinja2 + htmx, Pydantic. Kein Build, kein npm; Fremd-JS als Datei im Repo.
- Nur an `127.0.0.1`, fester konfigurierbarer Port (Vorschlag 8765); belegt → Abbruch. Jede Seite hat eine direkt öffenbare URL. Start per Windows-Verknüpfung mit Ladebalken; der Server beendet sich, wenn keine Seite mehr offen ist.
- Kontext: Nutzer global; Jahr global, je Seite übersteuerbar.
- Gestaltung: nur Desktop ab UWHD, kein Seiten-Scrollen (innen scrollende Bereiche erlaubt), wichtigste Infos immer sichtbar, Übersichtlichkeit hat Vorrang, der Platz wird genutzt. Hell und Dunkel über CSS-Variablen; ausgestaltet wird zuerst Dunkel. Tastatur wo sinnvoll.
- Absicherung: Middleware prüft `Host`; ändernde Anfragen brauchen `Origin` gleich dem eigenen Origin (`http://127.0.0.1:<port>` bzw. `http://localhost:<port>`) oder `Sec-Fetch-Site: same-origin`; kein CORS, kein Token. Strikte CSP ohne Inline-Skript, `nosniff`, Autoescape überall.
- Oberflächentexte stehen direkt in den Vorlagen, nur Deutsch.

## 7. Claude-Aufruf

Quellen: [Claude als Baustein](https://github.com/oiff2/MoarCoal/issues/7), [ADR 0007](adr/0007-absicherung-server-und-claude-aufruf.md).

- Ein einziger Aufrufbaustein hinter der Auslese-Schnittstelle der Datenebene; in Tests ein Fake.
- `claude -p --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --input-format stream-json --output-format stream-json` in einem leeren Wegwerfverzeichnis; Abbruch mit Fehler-Befund, wenn `init` Werkzeuge oder MCP-Server meldet. Ein Test prüft die Argumentliste.
- Dokument als base64-`document`- bzw. `image`-Block; Antwort gegen das JSON-Schema aus der Auslese-Vorlage, dann Pydantic; fremde Felder verworfen. Ergebnis ist immer ein Vorschlag.
- Gebaut in `extraction.py`: `Extractor`-Protokoll, `ClaudeExtractor` (echt) und `FakeExtractor`; Fehler (Abbruch, Zeitüberschreitung, ungültige Antwort, nicht unterstütztes Format) kommen als `ExtractionFailed` zurück, nicht als Ausnahme. Die Antwort ist ein JSON-Objekt, dessen Schlüssel die Felder der Vorlage sind, je Feld `value` und `location`.

## 8. Datenschutz

Quelle: [Sensible Werte](https://github.com/oiff2/MoarCoal/issues/14).

- Felder werden am Pydantic-Modell als `Sensitive[str]` markiert, einmal je Feldtyp. Bei Ausstellern nur, wenn sie Privatperson sind.
- Die Datenebene schreibt daraus `common/derived-denylist.txt`: ganze Werte ab 6 Zeichen, bei Namen und Anschriften zusätzlich Teile ab 6 Zeichen. `tools/privacy_guard.py` liest sie neben der handgepflegten Sperrliste, ohne Modelle zu importieren; fehlt sie, warnt es.
- Gilt für git, GitHub und das Protokoll der App (dort maskiert), nicht für Claude.

## 9. Glossar und Testkern

Quelle: [Glossar durchsetzen](https://github.com/oiff2/MoarCoal/issues/9).

Der schnelle Testkern (pytest) prüft:

- _Avoid_-Wörter aus `CONTEXT.md` in Vorlagen (mit kleiner Ausnahmeliste, z. B. Schweregrade);
- jeder `Code:`-Name existiert im Code; kein Typ trägt einen gemiedenen englischen Namen;
- mehr als 30 geprägte Begriffe → Warnung mit Verweis auf `glossar-review`;
- Arten sind über alle Module eindeutig;
- verwaiste Schlüssel- und Art-Aliasse;
- die Argumentliste des Claude-Aufrufs;
- Zyklen im Wertekatalog dürfen früh gewarnt werden (kein Verbot).

## 10. Bei der Zusammenführung aufgelöst

Frühere Entscheidungen, die von späteren ersetzt sind (hier gilt die spätere):

| Früher | Ersetzt durch |
|---|---|
| Wert = Summe seiner Einzelposten; „nicht vorhanden ≠ 0“ ([Contract](https://github.com/oiff2/MoarCoal/issues/2)) | Ergebnis einer Rechnung; noch nicht berechenbar / entfällt ([Zeitreihen](https://github.com/oiff2/MoarCoal/issues/16), [Abgeschaltetes Modul](https://github.com/oiff2/MoarCoal/issues/24)) |
| JSON „neben den Belegen“, `version`-Feld, alte Jahre beim Laden hochziehen ([Speicher](https://github.com/oiff2/MoarCoal/issues/3)) | eigenes Datenverzeichnis ([ADR 0003](adr/0003-belege-verweisen-statt-kopieren.md)), `schema`-Feld und Migration beim Start ([ADR 0004](adr/0004-migration-beim-start.md)) |
| Dokument verweist optional auf einen Vertrag; Notiz „an jedes Ding“ ([Bausteine](https://github.com/oiff2/MoarCoal/issues/4)) | Zuordnungen als Liste von Adressen; Notizen nur an Einträgen ([Kennungen](https://github.com/oiff2/MoarCoal/issues/20)) |
| Schnappschuss ohne Dateikopie ([Schnappschuss](https://github.com/oiff2/MoarCoal/issues/5)) | Kopie beim Einfrieren ([Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13)) |
| Abgeschaltet: „keine Einzelposten, kein Fehler“ ([Einhängen](https://github.com/oiff2/MoarCoal/issues/6)) | Aufzählung leer, sonst „entfällt“ ([Abgeschaltetes Modul](https://github.com/oiff2/MoarCoal/issues/24)) |
| Fehlender fremder Wert → „unvollständig“, Summe der übrigen; Zyklus → „nicht vorhanden“ ([Ketten](https://github.com/oiff2/MoarCoal/issues/12)); „unvollständig“ einfrieren ([Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13)) | noch nicht berechenbar, mit Grund eingefroren ([Zeitreihen](https://github.com/oiff2/MoarCoal/issues/16), [Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19)) |
| Skizze: Modul übergibt Belegstand an `item` ([Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19)) | Belegstand aus der Art der Fundstelle ([Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21)) |
| Skizze: `Store.read`/`Store.write` je Nutzer und Modul mit Datenobjekt `D` ([Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19)) | eingegrenzter Stand `ModuleState`, Vorgang aus Änderungen an Einträgen ([Interface der Datenebene](https://github.com/oiff2/MoarCoal/issues/26)) |

Echte Widersprüche, hier entschieden:

1. **Wiederfinden verschobener Dokumente** ([Dateistruktur](https://github.com/oiff2/MoarCoal/issues/10)) sollte „beim Zugriff den Pfad still aktualisieren und eine Notiz anlegen“. Das stößt sich mit „GET ändert nie“ ([ADR 0007](adr/0007-absicherung-server-und-claude-aufruf.md)), mit dem einen Schreibweg ([ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md)) und damit, dass eine Notiz Text eines Nutzers ist. **Entscheidung:** Beim Zugriff wird der eindeutige Treffer nur für diese Anfrage verwendet, dazu ein Hinweis-Befund „Dokument verschoben“ mit Aktion „Pfad übernehmen“. Der Knopf „Ablageorte prüfen“ (POST) übernimmt alle eindeutigen Treffer in einem Vorgang und schreibt ins Protokoll. Keine automatische Notiz.
2. **Doppelte Befunde für Ausstehendes**: [Befunde](https://github.com/oiff2/MoarCoal/issues/11) nennt „ausstehende Einzelposten“, [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) den Befund am Erwarteten Beleg. **Entscheidung:** Der Befund „ausstehend“ hängt am Erwarteten Beleg je Zeitraum, nicht an jedem Einzelposten; der Belegstand der Einzelposten zeigt sich am Wert.
3. **Glossar-Nachträge** aus [Python-Schnittstelle](https://github.com/oiff2/MoarCoal/issues/19) lagen nur auf dem Prototyp-Branch und sind jetzt in `CONTEXT.md` übernommen: Code-Namen `LineItem`, `Locator`, `Backing`, `Workings`, `Subject`, `Period`, `KeyDate`, `NotYetComputable`, die Belegstand-Reihenfolge und „ohne Einzelposten belegt“.
4. **Quelle „Übertragungsprotokoll“** im Glossar widersprach „die Fundstelle nennt, ob ausgelesen oder eingelesen“. Die Quelle heißt jetzt **Einlesung**; **einlesen** hat einen eigenen Glossareintrag. Die Modulanmeldung im Glossar nennt jetzt alle angemeldeten Teile.

## 11. Offen für den Bau

Bewusst nicht entschieden; das Gerüst legt es beim Bauen fest, ohne dass sich an den Entscheidungen oben etwas ändert:

- Dateinamen und -zuschnitt je Baustein und Modul unter `users/<id>/`; Ablage der Nutzerliste; Ort des Start-Archivs (nicht in sich selbst sichern) und wie viele behalten werden.
- Format des Schlüssels im Wertekatalog (die Skizze nutzt `<bereich>.<name>`, z. B. `property.loan_interest`).
- Wie der Server erkennt, dass keine Seite mehr offen ist.
- Form des Fingerabdrucks eines Befunds und der Prüfsumme eines Eintrags im Formular.
- Darstellung des Rechenwegs und des Anzeigebausteins im Einzelnen.
- Wie eine Änderung Gespeichertes ohne eigene Adresse nennt (Ausblendung, Vorschlag, Ausnahme eines Erwarteten Belegs): über den Eintrag, an dem es hängt, oder über einen eigenen natürlichen Schlüssel.

## 12. Außerhalb

Siehe Abschnitt „Out of scope“ der [Karte](https://github.com/oiff2/MoarCoal/issues/1): Übernahme der Kohlebau-Daten, Inhalte der Module (je eigene Karte), Plugin-Laufzeit, Versionierung der Eingaben, Tooltips je Begriff, gemeinsames Eigentum mehrerer Nutzer.
