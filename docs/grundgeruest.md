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

**Abschnitt 2** ([#46](https://github.com/oiff2/MoarCoal/issues/46)), sobald der Durchstich steht: Auslesen mit Claude als Vorschlag mit Bestätigung (Abschnitt 7), am Beispiel des EStB-Abgleichs; Schnappschuss bei Abgabe, ohne Dokumentkopie; Erwarteter Beleg in einfacher Form; Ausblenden von Befunden; Eingang.

**Später, wenn es gebraucht wird**:

- Journal über mehrere Dateien ([ADR 0006](adr/0006-schreibweg-vorgang-mit-journal.md)): sobald Vorgänge regelmäßig mehrere Dateien schreiben
- Migration beim Start und Start-Archiv ([ADR 0004](adr/0004-migration-beim-start.md)): bei der ersten Schemaänderung
- Zusammenführen mit Alias (`Merge`)
- Neu auslesen mit Vorlagenfassung
- Neu einlesen beim Start, mit Befund Neueinlesung (Fingerabdruck = Prüfsumme der Neueinlesung, [#57](https://github.com/oiff2/MoarCoal/issues/57)): sobald sich eine Einlese-Regel ändert
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
| Dokumentart | Code | angemeldet von Modulen, einige allgemeine von der Datenebene; legt fest, ob es einen Bezugszeitraum gibt und ob je Bezugszeitraum und Nutzer nur ein Dokument erlaubt ist (`unique_per_period`, [#87](https://github.com/oiff2/MoarCoal/issues/87)) | [Was Module speichern](https://github.com/oiff2/MoarCoal/issues/21) |
| Aussteller | gemeinsam | Name, weitere Namen (Aliasse), Merkmal Privatperson; Anschrift und Nummern erst, wenn ein Modul sie braucht; Zusammenführen als bewusster Ausnahmeweg (siehe Zuschnitt unten) | [Bausteine](https://github.com/oiff2/MoarCoal/issues/4), [Sensible Werte](https://github.com/oiff2/MoarCoal/issues/14), [Zuschnitt](https://github.com/oiff2/MoarCoal/issues/67) |
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

Was **nicht** zur Datenebene gehört: Konten und Buchungen, Immobilie, Darlehen, Fahrten, Steuerzeilen. Altjahre (2017–2024) sind normale Dokumente (Übertragungsprotokoll, EStB), aus denen das Steuerjahr belegte Werte macht.

**Zuschnitt des Ausstellers** ([#67](https://github.com/oiff2/MoarCoal/issues/67)):

- **Felder:** Name, Aliasse (weitere Namen, auch der volle Firmenname) und das Merkmal Privatperson. Keine Art (Unternehmen und Behörde unterscheiden sich in MoarCoal nicht), kein juristischer Name; Anschrift und Nummern erst bei Bedarf. Gemeinsam für alle Nutzer.
- **Am Dokument freiwillig.** Der Hinweis-Befund „Dokument ohne Aussteller“ meldet die Lücke; keine Migration, bestehende Dokumente bekommen ihn nachträglich über die Dokumentseite. Der Erwartete Beleg bleibt in der einfachen Form ohne Aussteller.
- **Aufnehmen kompakt:** ein Suchfeld über Name und Aliasse, darunter die klickbare Trefferliste; Treffer wählen. Ohne Klick heißt Text „neu anlegen“ (Häkchen Privatperson in derselben Zeile, nur sichtbar, solange Text steht und nichts gewählt ist), leer heißt „kein Aussteller“. Ähnlicher Name: zusätzlich „Neuer Alias: ‹Text›“ je Treffer. Vorbelegt ist der zuletzt für die Dokumentart verwendete Aussteller (nur Oberfläche, nichts gespeichert).
- **Zusammenführen ist die Ausnahme:** Normalfall ist ein neuer Alias. Zusammenführen nur auf der Seite des Ausstellers, mit Folgenseite (betroffene Dokumente und Erwartete Belege) und ausdrücklicher Bestätigung; Name und Aliasse der Quelle werden Aliasse des Ziels, die Kennung der Quelle verweist danach auf das Ziel. Keine Vorschläge der App, nie von selbst.
- **Seite** `/aussteller`: Katalog (Name, Aliasse, Zahl der Dokumente und Erwarteten Belege, Suche), Detail (ändern, Dokumente, Erwartete Belege), Löschen nur ohne Verweise. Ihr Platz in der Navigation: Kategorie Allgemein, neben Belege ([#63](https://github.com/oiff2/MoarCoal/issues/63)).
- **Slices:** (1) Datenebene: Eintragsart, Feld am Dokument, `display_name`/`url`, Befund; (2) Aufnehmen-Formular und Ändern an der Dokumentseite; (3) Seite mit Katalog, Detail, Aliasse, Löschen; (4) Zusammenführen; später: Auslese schlägt den Aussteller vor, Erwarteter Beleg bekommt den Aussteller.

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
- **Stand des Baus (Durchstich, [#34](https://github.com/oiff2/MoarCoal/issues/34)):** Die Modulanmeldung trägt `finding_kinds` (`FindingKind`) und `findings` (eigener Stand, Werte, Jahr -> Befunde). `Values.finding_list(user, year)` rechnet alle Zeitraumwerte des Jahrs (Stichtagswerte noch nicht), sammelt Zyklus-Befunde und die der Module, Fehler zuerst; die Seite `/befunde?year=…` zeigt sie (Jahr vorerst Vorgabe 2025), die Seite der Anlage N zeigt dieselben. `Finding.href` führt zur Stelle der Prüfung. Abgleich in `modules/tax_year/comparison.py` gegen das zuletzt aufgenommene Protokoll des Jahrs (`Document.taken_in_at`): Abweichung, Feld fehlt, mehrdeutig (Tage/km mehrfach) je Warnung; Feld ohne E-Kennung ein Hinweis; kein Abgleich bei Werten, die nicht berechenbar sind oder entfallen, und ohne Protokoll. Exakt und ohne Toleranz gegen den gerundeten Feldwert (das Feld rundet nach `Rounding` und `Direction`, die Rechnung des Felds hält den Rundungsschritt im Rechenweg fest; Recherche in [`recherche-runden-anlage-n.md`](recherche-runden-anlage-n.md)); bei reiner Rundungsabweichung nennt der Text Differenz und Richtung; EUR-Zeilen mit gleicher E-Kennung summiert. Ausblenden: siehe nächsten Eintrag.
- **Stand des Baus (Abschnitt 2, [#47](https://github.com/oiff2/MoarCoal/issues/47)):** `Finding` trägt einen `fingerprint` (Standard: SHA-256 des Texts; Hilfsfunktion `fingerprint(*teile)` in `values/findings.py`) und erkennt sich an `identity` = Befundart + Ziel als Text (`target_text`); `target` ist `ValueRef` oder `EntryAddress`. Fingerabdrücke: Zyklus die beteiligten Schlüssel, doppelte Fundstelle Wert und Fundstelle, Abgleich E-Kennung, Wert und Inhalt der Protokollzeilen (Feld ohne E-Kennung: Schlüssel und Bezeichnung), Arbeitsmittel-Hinweis der Text. `Dismissal` (Ausblendung, `storage/dismissals.py`, Format `datenebene/1`, Datei `users/<nutzer>/dismissals.json`): Befundart, Ziel, Fingerabdruck, Notiz (Pflicht, nicht leer) und Datum. `Values.finding_list` liefert eine `FindingList` (`visible`, `hidden` mit der verbergenden Ausblendung, `earlier` mit der jüngsten früheren Ausblendung eines zurückgekehrten Befunds, `hidden_errors`); eine frühere Ausblendung bleibt gespeichert. Seite `/befunde`: Formular „Ausblenden“ je Befund (POST `/befunde/ausblenden` mit Befundart, Ziel, Fingerabdruck und Notiz; der Server prüft gegen die aktuelle Liste, 409 bei geändertem Stand, 422 ohne Notiz), Zähler der ausgeblendeten Befunde mit Fehlern gesondert, `?ausgeblendet=1` zeigt sie samt Knopf „Einblenden“ (POST `/befunde/einblenden`, löscht die Ausblendung). Die Seite der Anlage N zeigt nur die sichtbaren Befunde, ohne Formular. Logik in `dismissals.py`.
- **Stand des Baus (Abschnitt 2, [#55](https://github.com/oiff2/MoarCoal/issues/55)):** `ExpectedDocument` (Erwarteter Beleg in einfacher Form, `storage/expected_documents.py`, Datei `users/<nutzer>/expected_documents.json`, Format `datenebene/1`): Dokumentart (nur Arten mit Bezugszeitraum), Beginn- und Endjahr (Ende offen erlaubt, jährlich) und Beschreibung. Ein Jahr ist erfüllt, wenn ein Dokument des Nutzers dieser Dokumentart einen Bezugszeitraum hat, der das Jahr berührt; ob sein Vorschlag bestätigt ist, spielt keine Rolle. Befunde (Hinweis, `expected_documents.py`, von `Values.finding_list` für das Jahr der Liste gesammelt): `expected_document_pending` und `expected_document_duplicate` (mehrere passende Dokumente), Ziel als Text `<Adresse des Erwarteten Belegs>@<Jahr>` (je Jahr ein eigener Befund, Ausblenden gilt nur für das Jahr), Fingerabdruck bei „ausstehend“ Dokumentart und Beschreibung, bei der Dublette die Dokumente. Fundstelle `ExpectedDocumentLocator` (`values/model.py`, Belegstand ausstehend); kein Modul nutzt sie bisher. Seite `/belege/erwartet` (Reiter der Belege-Seite, `/erwartete-belege` leitet mit 308 um) (`expected_documents_pages.py`): Stand je Jahr (bei offenem Ende bis `DEFAULT_YEAR`), anlegen, ändern, löschen mit Prüfsumme. Vorschlag Aussteller ([#81](https://github.com/oiff2/MoarCoal/issues/81)): `previous_year_issuer` (`expected_documents.py`) fragt dieselbe Erfüllungsregel für das Vorjahr und nimmt den Aussteller des ersten erfüllenden Dokuments mit Aussteller; berechnet, kein Feld, `Merge` unberührt. Die Seite zeigt „Aussteller im Vorjahr: ‹Name›“ mit Link (Liste und `/belege/erwartet/{id}`) für das letzte angezeigte Jahr; die Erfüllung bleibt unverändert.
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
8. **Ergänzung beim Aufnehmen** ([#49](https://github.com/oiff2/MoarCoal/issues/49)): Eine Dokumentart kann neben der Einlese-Regel eine Funktion `after_take_in(document, entries, values) -> Änderungen` haben. `take_in` ruft sie auf einem vorläufigen Stand auf, der Dokument und eingelesene Einträge schon enthält (sie sieht `Values` also *nach* dem Aufnehmen), und schreibt Dokument, Einlesung und Ergänzung in **einem** Vorgang. Sie kann das Aufnehmen nicht ablehnen; ein Fehler darin ist ein Programmfehler. Beim Neu-Einlesen läuft sie nicht erneut, denn sie gehört zum Zeitpunkt des Aufnehmens (z. B. Schnappschuss bei Abgabe, 3.7). Die Einlese-Regel bleibt rein und wertet nichts aus.
9. **Bestätigte Felder lesen statt übernehmen** ([#52](https://github.com/oiff2/MoarCoal/issues/52)): Module kopieren bestätigte Felder nicht in eigene Einträge, sondern lesen sie über die Datenebene, z. B. `ModuleState.confirmed_fields(document) -> {Feldschlüssel: (Inhalt, Fundstelle)}`. Das liefert nur bestätigte Felder aus dem neuesten Vorschlag des Dokuments; bei Korrekturen steht der korrigierte Inhalt an der Stelle des ausgelesenen. Ein Feld der Auslese-Vorlage mit Einheit kommt als `Decimal`, gleich ob Claude eine Zahl oder einen deutschen Zahltext geliefert hat oder der Nutzer korrigiert hat (`TemplateField.read`); Bestätigen weist ein solches Feld ab, wenn sein Inhalt keine Zahl ist. Felder ohne Einheit kommen unverändert. Die Fundstelle (`DocumentLocator`) nennt Dokument, Quelle (Dokumentauslesung oder Einlesung), Feldschlüssel der Vorlage und die Stelle im Dokument als Klartext; sie nennt keinen bestimmten Vorschlag, bleibt also über Neu auslesen gültig. Belegstand belegt, auch bei Korrekturen. Punkt 6 („gehört zu bestehendem Eintrag“) wird erst gebraucht, wenn ein Modul Felder in eigene Einträge übernimmt, und ist bis dahin „Später“.

### 3.7 Schnappschuss

Quellen: [Schnappschuss](https://github.com/oiff2/MoarCoal/issues/5), [Dokumente nach Abgabe](https://github.com/oiff2/MoarCoal/issues/13), [ADR 0001](adr/0001-schnappschuss-statt-sperre.md), [ADR 0003](adr/0003-belege-verweisen-statt-kopieren.md).

- Ausgelöst von einem Modul zu einem Anlass (erst: Abgabe, belegt durch das Übertragungsprotokoll). Der EStB erzeugt keinen. Berichtigungen ergeben einen neuen Schnappschuss daneben. Altjahre vor 2025 haben keine.
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
- Geschrieben wird nur in einem **Vorgang** hinter einer einzigen Schreibsperre: prüfen (Pydantic) → Prüfsummen vergleichen (Datei: Handänderung abweisen; Eintrag: veralteten Tab mit „inzwischen geändert“ abweisen) → `.backup/` → temporäre Dateien mit `fsync` → Journal → umbenennen → Journal löschen → Stand tauschen. Danach ggf. abgeleitete Sperrliste neu schreiben; scheitert das, entsteht ein Befund (Warnung), kein Abbruch (ADR 0006).
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

**Stand des Baus (Abschnitt 2, [#48](https://github.com/oiff2/MoarCoal/issues/48)):** `Store.list_site_files(site)` listet die Dateien eines Ablageorts rekursiv als `SiteFile` (Ablageort, Pfad, Größe, SHA-256) mit den Regeln von `read_site_file`: Verzeichnis-Links werden nicht verfolgt, Dateien mit Ziel außerhalb, über 50 MB oder unlesbare fehlen; der SHA-256 wird nach Datei, Größe und Änderungszeit zwischengespeichert. `HiddenFile` (Ausblendung im Eingang, `storage/hidden_files.py`, Format `datenebene/1`, Datei `common/hidden_files.json`, Eigentümer `common`) trägt SHA-256, Ablageort und Pfad (zur Anzeige) und eine freiwillige Notiz; unter „Ausgeblendet“ blendet jeder Nutzer sie wieder ein (POST `/eingang/einblenden` mit SHA-256 und Prüfsumme, löscht die `HiddenFile`). `incoming.py`: `incoming_files(Dateien, Stand, Nutzer)` ist der Eingang eines Nutzers (nicht von ihm aufgenommen, nicht ausgeblendet, gleicher Inhalt an mehreren Stellen einmal mit dem ersten Pfad), `hide_file` blendet aus. Seite `/eingang` (`incoming_pages.py`, Navigation der App): je Datei Ablageort, Pfad, Größe, Formular „Aufnehmen“ (POST `/eingang/aufnehmen` mit SHA-256, Dokumentart aus allen Modulanmeldungen und Jahr, das Feld Jahr nur bei Arten mit Bezugszeitraum sichtbar, per CSS ohne Skript; die Datei wird über den SHA-256 im aktuellen Eingang gesucht, 409 wenn sie fehlt, Abweisungen von `take_in` mit 422 in der Zeile) und „Ausblenden“ (POST `/eingang/ausblenden` mit SHA-256 und Notiz). Nach dem Aufnehmen 303 zur ersten `entry_url` eines eingelesenen Eintrags, sonst zurück in den Eingang; das Steuerjahr nennt dafür seine Seite des Protokolls. Das Formular mit Ablageort und Pfad auf der Seite des Steuerjahrs entfällt. Befund `incoming_files` („n Dateien im Eingang“, Hinweis, Ziel „eingang“, Link `/eingang`) je Nutzer; sein Fingerabdruck ist die sortierte Menge der SHA-256. `Finding.target` darf dafür auch ein Text sein. `Values` bekommt die Liste der Dateien nur als Funktion und ruft sie erst beim Bilden der Befundliste.

**Stand des Baus (Abschnitt 2, [#50](https://github.com/oiff2/MoarCoal/issues/50)):** `DocumentKind.after_take_in(document, entries, values) -> Sequence[Change]` ist gebaut (3.6 Punkt 8); `take_in` bekommt dafür `values_on: Callable[[State], Values]` (Pflicht, sobald die Art eine Ergänzung hat) und ruft sie auf einem vorläufigen Stand mit Dokument und Einlesung auf. `Snapshot` (`storage/snapshots.py`, Datei `users/<id>/snapshots.json`, Format `snapshot/1`, wird nie migriert) trägt Anlass (`Occasion`, vorerst Abgabe), Zeitpunkt, Modul, Dokument, Zeitbezug und die eingefrorenen Werte (`FrozenValue`: Ergebnisart, Betrag, Belegstand, Einzelposten mit Fundstelle als Klartext, Rechenweg, Kette; Beträge mit Anzeigetext). Die Werte, auf die sich ein Wert stützt (`FrozenItem.uses`, `chain`), stehen als eigene Werte mit `requested=False` daneben. `values/snapshots.py`: `freeze(values, user, keys, time)`, `compare(snapshot, values) -> list[Deviation]` (Abweichung je Stufe: Betrag, Ergebnisart, Einzelposten hinzugekommen/weggefallen/geändert; Einzelposten werden über Bezeichnung und Fundstelle zugeordnet), `latest_snapshots` (je Modul, Anlass und Zeitbezug der neueste) und der Befund der Datenebene „Eingefrorener Wert war noch nicht berechenbar“ (Fehler, nur für verlangte Werte des neuesten Schnappschusses). Das Steuerjahr friert beim Aufnehmen eines Protokolls die Schlüssel von `FORMS[Jahr]` ein (ohne Felder des Jahrs: kein Schnappschuss) und meldet je Feld die Warnung „Abweichung zum Schnappschuss“ gegen den neuesten Schnappschuss des Jahrs; die Seite der Anlage N zeigt den eingefrorenen Wert in der Spalte „Bei Abgabe“. Keine Dokumentkopie beim Einfrieren (Abschnitt 2); `ModuleState.snapshots()` liefert die Schnappschüsse, die das Modul ausgelöst hat.

**Stand des Baus (Abschnitt 2, [#54](https://github.com/oiff2/MoarCoal/issues/54)):** Das Steuerjahr meldet die Dokumentart `assessment` (Einkommensteuerbescheid, EStB, mit Bezugszeitraum, `modules/tax_year/assessment.py`) mit Auslese-Vorlage (`TEMPLATE`, Fassung 1: die Positionen, die der EStB druckt; doppelt gedruckte Bezeichnungen tragen ihren Block in Klammern). Der Katalog der Anlage N 2025 enthält alle bekannten Felder (23, Quelle: Übertragungsprotokoll 2025): `FormField.computed` ist nur bei den drei Feldern mit Quelle in Arbeit wahr; die übrigen haben keinen Ausgewiesenen Wert und keinen Schnappschuss-Wert, die Seite zeigt „wird noch nicht berechnet“, `FormField.unit` ist leer bei Feldern ohne Betrag (Text, Ja/Nein). `FormField.assessment` nennt die Positionen der Vorlage, deren Summe dem Feld entspricht; `printed_rounded` markiert Positionen, die der EStB in ganzen Euro druckt. Der EStB-Abgleich (`comparison.assessment_findings`) liest die bestätigten Positionen des neuesten EStB des Jahrs, zu dem schon Positionen bestätigt sind (`current_assessment`), über `ModuleState.confirmed_fields` und vergleicht sie mit dem eingefrorenen Wert des neuesten Schnappschusses (`FormField.matches_assessment`: Spanne bei ganzen Euro (einen Euro darunter bis einen darüber) und gerundet gedruckten Positionen, sonst exakt, Vorzeichen ignoriert; eine bestätigte leere Position zählt 0, ein entfallener Wert 0, ein noch nicht berechenbarer fehlt). Befundarten `tax_year.assessment_deviation` (Warnung, beide Beträge, Link zum Dokument) und `tax_year.assessment_no_snapshot` (Hinweis, nur wenn ein bestätigtes Feld berechnet wird). Die Seite der Anlage N zeigt die Spalte „Laut EStB“. Offen: Positionen mit Vorzeichen (z. B. Verlust aus V+V) und Produkte/Höchstbeträge der Spannenregel, bis ein Feld sie braucht.

**Stand des Baus (Abschnitt 2, [#56](https://github.com/oiff2/MoarCoal/issues/56)):** Lauf mit echtem Übertragungsprotokoll, EStB 2025 und dem echten `claude`. Widerlegt: `claude -p --output-format stream-json` verlangt `--verbose` (ohne bricht der Aufruf ab; Argumentliste und Test angepasst). Bestätigt: `init` meldet mit der festen Argumentliste keine Werkzeuge und keine MCP-Server (`init` führt dazu weiter `skills` und `plugins` auf, die `--setting-sources ""` nicht abschaltet; sie sind ohne Werkzeuge wirkungslos und werden nicht geprüft). Das Übertragungsprotokoll muss die HTML-Fassung aus Mein ELSTER sein, das PDF desselben Protokolls weist das Aufnehmen ab. Ein Schnappschuss entsteht nur beim Aufnehmen des Protokolls; ein früher aufgenommenes Dokument bekommt keinen nachträglich, und es gibt noch keinen Weg, ein Dokument zu entfernen und neu aufzunehmen (im Lauf von Hand aus dem Datenverzeichnis gelöscht).

**Stand des Baus (Aussteller, [#68](https://github.com/oiff2/MoarCoal/issues/68)):** `Issuer` (`storage/issuers.py`, Format `datenebene/1`, Datei `common/issuers.json`, Eigentümer immer `common`) trägt Name, Aliasse und `private_person`; `display_name` und `url` (`/aussteller/<Kennung>`; `web.entry_url` löst die Adresse auf). Die Seite (`issuer_pages.py`, [#70](https://github.com/oiff2/MoarCoal/issues/70)) zeigt den Katalog mit Suche in Name und Aliassen und je Aussteller die Zahl der Dokumente und Erwarteten Belege des Nutzers (jeder Eintrag, der auf ihn verweist; der Erwartete Beleg trägt noch keinen Aussteller, die Zahl ist bis dahin 0); das Detail ändert Name, Aliasse und Privatperson (mit Prüfsumme) und löscht nur ohne eigene Verweise, sonst steht dort die Liste der Verweise. Anlegen folgt mit dem Aufnehmen-Formular (Slice 2). Zusammenführen ([#71](https://github.com/oiff2/MoarCoal/issues/71)): Änderung `Merge(source, into, expected, expected_into)` mit beiden Prüfsummen, ganz oder gar nicht, nur Aussteller; Name und Aliasse der Quelle werden Aliasse des Ziels (ohne Dubletten, Groß/klein egal), `Issuer.merged_ids` hält die Kennung der Quelle, `State.resolve` löst sie auf das Ziel auf (die Seite leitet mit 308 um), `Document.issuer` wird umgehängt, das Ziel gilt als Privatperson, wenn eine von beiden es war. Seite: `/aussteller/{id}/zusammenfuehren` (GET Folgenseite, POST mit Häkchen als Bestätigung). `Document.issuer` (`EntryAddress | None`) ist freiwillig, ältere `documents.json` laden unverändert. `Store.apply` prüft Verweise nach dem Vorgang: Gelöschtes, auf das ein verbleibender Eintrag verweist (jedes Adressfeld, `referenced_addresses`), weist es mit „Wird noch verwendet.“ ab (gilt für alle Arten); ein Dokument mit einem Aussteller, den es nicht gibt, wird abgewiesen. Befund `document_without_issuer` (Hinweis, Ziel das Dokument, Link `/dokumente/<Kennung>`, `issuers.py`) je Dokument des Nutzers ohne Aussteller. Eindeutigkeit ([#80](https://github.com/oiff2/MoarCoal/issues/80)): Name und Aliasse aller Aussteller sind zusammen eindeutig (`name_key`: ohne Groß-/Kleinschreibung und Randleerzeichen, auch innerhalb eines Ausstellers); `Store.apply` prüft den Zustand nach dem ganzen Vorgang wie die Verweise und weist den betroffenen Aussteller mit „Name gibt es schon.“ ab, Namen-Verschieben im selben Vorgang (Zusammenführen) geht. Das Aussteller-Feld nennt beim Anlegen und beim Alias den Aussteller, der den Namen schon trägt. Sperrliste: `Issuer.sensitive_values()` liefert Name und Aliasse nur bei einer Privatperson, `denylist_lines` bildet daraus die Werte (ganz und Teile ab 6 Zeichen); `Store` schreibt `common/derived-denylist.txt` (nur Werte, eine je Zeile, sortiert) beim Öffnen und nach jedem erfolgreichen `apply` neu, aber nur, wenn sich der Inhalt ändert; scheitert das Schreiben, gilt der Vorgang trotzdem, es entsteht ein Befund und das Protokoll warnt (seit [#97](https://github.com/oiff2/MoarCoal/issues/97), siehe dort). `tools/privacy_guard.py` liest die Datei zusätzlich zu `~/.config/moarcoal/sperrliste.txt` aus `MOARCOAL_DATA_DIR` bzw. `~/MoarCoal`, ohne Modelle zu importieren; fehlt Datei oder Verzeichnis, passiert nichts. Sensibel ist bisher nur Name und Aliase einer Privatperson.

**Stand des Baus (Aussteller, [#69](https://github.com/oiff2/MoarCoal/issues/69)):** Das Aussteller-Feld ist ein wiederverwendbarer Baustein: Vorlage `_issuer_field.html` (Makro `issuer_field`, htmx) und `issuer_field.py` (`GET /aussteller-suche` schreibt nie; `resolve_issuer` macht aus `issuer_choice` (leer, `id:…`, `alias:…`; leer mit Text legt neu an, seit #88 auch `new` nur noch zur Verträglichkeit), `issuer_text` und `issuer_private` den Aussteller samt Änderungen für Anlegen oder Alias). `take_in` nimmt `issuer` und `issuer_changes` und schreibt sie im selben Vorgang wie das Dokument; `POST /dokumente/{id}/aendern` ändert oder entfernt ihn (seit #74 zusammen mit Art und Jahr). Vorbelegt ist der zuletzt für die Dokumentart verwendete Aussteller (aus den Dokumenten berechnet), am Dokument der gewählte. Die Ablage zeigt den Aussteller aufgenommener Dateien.

**Stand des Baus (Dokumentart je Jahr nur einmal, [#87](https://github.com/oiff2/MoarCoal/issues/87)):** `DocumentKind.unique_per_period` (Standard aus, nur mit Bezugszeitraum; gesetzt für Übertragungsprotokoll und EStB). `Store.apply` kennt keine Dokumentart; die Prüfung steht deshalb in `take_in` und `change_document` (`documents.py`, beide schreiben über `store.apply`): gibt es für Nutzer, Art und Jahr schon ein anderes Dokument, kommt `IntakeRejected` mit „Existiert bereits: ‹Art› ‹Jahr›“ und dem vorhandenen Dokument (`existing`; Aufnehmen-Seite und Dokumentseite verlinken es), es wird nichts geschrieben. Das Dokument zählt nicht als Kollision mit sich selbst. Frei wird die Art durch Löschen des vorhandenen Dokuments; einen Ersetzen-Weg gibt es nicht. Vorhandene Dubletten bleiben; Befundart `document_duplicate` (Hinweis, Ziel das Dokument, Link `/dokumente/<Kennung>`, `duplicate_findings` in `documents.py`, von `Values.finding_list` gesammelt) je beteiligtem Dokument des Nutzers.

**Stand des Baus (Prüfungen je Eintragsart, [#97](https://github.com/oiff2/MoarCoal/issues/97)):** `Store` kennt keine einzelne Eintragsart mehr; was der Schreibweg je Art zusätzlich tut, steht optional in ihrem `EntryKind`: `check(Eintrag, Einträge nach dem Vorgang) -> Abweisung | None` läuft für jeden geschriebenen Eintrag (`Put`, Ziel eines `Merge`) gegen den Stand nach dem ganzen Vorgang (Aussteller: „Name gibt es schon.“, Dokument: „Aussteller existiert nicht.“); `denylist(alle Einträge der Art) -> Werte` liefert die Werte der abgeleiteten Sperrliste (Aussteller: `denylist_lines`); `merge(Quelle, Ziel) -> neues Ziel` erlaubt `Merge` für die Art (Aussteller: `merge_issuers`). Beim `Merge` zeigt danach jedes direkte Feld eines Eintrags, das auf die Quelle verweist, auf das Ziel (`with_reference_moved`); `State.resolve` löst über das Feld `merged_ids` des Ziels auf. Scheitert das Schreiben der Sperrliste (beim Öffnen oder nach `apply`), trägt der neue Stand `State.denylist_failed`, und `Values.finding_list` meldet den Befund `denylist_not_written` (Warnung, Ziel „sperrliste“, ohne Link); beim nächsten erfolgreichen Schreiben verschwindet er.

**Stand des Baus (Belege, [#74](https://github.com/oiff2/MoarCoal/issues/74)):** Reiter Dokumente unter `/belege/dokumente` (`document_list.py`): alle Dokumente des Nutzers nach Pfad, Filter Suche (Pfad, Ablageort, Art, Name und Aliasse des Ausstellers), Art (auch „Beleg“), Jahr (Bezugszeitraum berührt das Jahr) und Aussteller (auch „ohne“), alle zugleich; Liste links, rechts Formular und Vorschau wie in der Ablage (Pfeiltasten und Enter ebenso). Der Zustand wird abgeleitet: „zu bestätigen“, wenn der neueste Vorschlag offene Felder hat, sonst „fertig“, ohne Art „Beleg“. Ändern (`POST /dokumente/{id}/aendern`, Vorlage `_document_form.html`, auch auf der Seite des Dokuments): der Aussteller immer; Art und Jahr nur, solange kein anderer Eintrag auf das Dokument verweist (`references_to`: Einlesung, Vorschlag, Schnappschuss, Abgebrochene Auslesung, …), sonst fehlen die Felder im Formular und der Server weist sie ab; „Beleg“ (ohne Art) ist wählbar. Wechselt die Art, liest die Einlese-Regel der neuen Art die Datei ein (scheitert sie, bleibt alles; die Ergänzung beim Aufnehmen läuft nicht). Löschen (`POST /dokumente/{id}/loeschen` mit Prüfsumme) nimmt nur das Dokument weg, die Datei ist in der Ablage wieder offen; bei Verweisen steht statt des Knopfs ihre Liste, und `Store.apply` weist es ohnehin ab.

**Stand des Baus (Belege, [#89](https://github.com/oiff2/MoarCoal/issues/89)):** Der Kopf eines Dokuments (Aussteller, Ändern, Vorschlag bestätigen, Auslesen) ist das Makro `document_detail` in `documents/_detail.html`, gespeist von `document_detail(request, document)` (`document_list.py`); er steht rechts im Reiter Dokumente und in der Ablage (aufgenommene Datei) und auf `/dokumente/{id}`, das für direkte Links und für die POST-Routen bleibt (seit [#95](https://github.com/oiff2/MoarCoal/issues/95) nur noch Umleitung und POST-Routen). Aufnehmen (Art mit Auslese-Vorlage), Auslesen, Bestätigen und Ändern leiten auf `/belege/dokumente?dokument=ID`; das Feld `from` der Formulare entfällt. Der Vorschlag ist eine Liste (`ul.vorschlag`, je Feld eine Zeile) statt einer Tabelle. Ausgeblendete: `selected_hidden` in `site_pages._page` (Auswahl über `?datei=<sha256>` wie in der Ablage), Vorschau über `/belege/datei/{sha256}`, solange die Datei im Ablageort liegt.

**Stand des Baus (Belege, [#95](https://github.com/oiff2/MoarCoal/issues/95)):** Die Seite `/dokumente/{id}` (`documents/show.html`) entfällt; `GET /dokumente/{id}` leitet mit 308 auf `/belege/dokumente?dokument=ID` um (wie `/eingang`). Diese Adresse baut allein `document_url` (`storage/documents.py`, als `Document.url`, wie `Issuer.url`); sie nutzen Befunde (ohne Aussteller, Dublette, Vorschlag, Abgleich), Erwarteter Beleg, Aussteller-Detail und -Zusammenführen, die Abweisung „Existiert bereits“ (Makro `rejection` in `_belege.html`, in Ablage und Reiter) und die Weiterleitungen nach dem Aufnehmen und den POST-Routen. Unter `/dokumente/{id}` bleiben nur die POST-Routen (`aendern`, `loeschen`, `auslesen`, `bestaetigen`) und die Datei-Route `/datei` (`document_pages.py`); ihre Abweisungen rendern den Reiter mit dem Dokument, der Meldung und der abgewiesenen Eingabe (`documents_page` in `document_list.py`). Art, Jahr und Aussteller aus dem Formular liest für Aufnehmen und Ändern einmal `read_document_choice` (`document_list.py`), samt der Meldung „Steuerjahr: ganze Zahl, z. B. 2025“; Abweisungen kommen dort wie von `take_in` als `IntakeRejected`.

**Stand des Baus (Belege, [#92](https://github.com/oiff2/MoarCoal/issues/92)):** Jede offene Datei und jeder Ordner der Ablage hat in der Zeile den Knopf „Ausblenden“ (`POST /belege/ausblenden-direkt`, Datei über `sha256`, Ordner über `site` und `path`; zurück auf `/belege?stand=…`); das Formular rechts mit Notiz bleibt. Ein Ordner ist die zweite Eintragsart `HiddenFolder` (Ablageort + Pfad, Eigentümer `common`, Datei `common/hidden_folders.json`), `HiddenFile` bleibt unverändert, denn ein Ordner hat keinen SHA-256. `in_hidden_folder` (`incoming.py`) gilt in `incoming_files` und `site_rows`, also auch für Zähler und Navigation; spätere Dateien darunter sind mit ausgeblendet, aufgenommene Dateien bleiben im Baum. Der Pfad folgt den Regeln von `Store.read_site_file` und muss mindestens eine aufgelistete Datei enthalten (`folder_path_error`). „Ausgeblendet (n)“ zeigt einen ausgeblendeten Ordner als eine Zeile mit Dateizahl und „Wieder einblenden“ (`POST /belege/einblenden-ordner`, mit Prüfsumme wie bei Dateien).

**Stand des Baus (Belege, [#76](https://github.com/oiff2/MoarCoal/issues/76)):** Vorbelegen aus dem Namen in `prefill.py` (`prefill_from_name(state, kinds, path)` liefert `Prefill(issuer, year, kind)`, bei jedem Aufruf der Seite `/belege?datei=` berechnet, nichts gespeichert, nur für offene Dateien und nur ohne abgewiesene Eingabe). Je Feld nur ein eindeutiger Treffer: Aussteller, wenn genau einer mit Name oder Alias (ganze Wörter, ab 3 Zeichen, Trenner wie `_ - . /` egal) im Pfad steht; Jahr, wenn der Pfad genau ein Jahr 2000 bis 2100 als Zahl oder Datum (`2025-03-14`, `14.03.2025`, `20250314`) enthält; Art, wenn genau eine Dokumentart ein Namensmuster (`DocumentKind.name_patterns`, reguläre Ausdrücke ohne Groß-/Kleinschreibung gegen den Pfad) trifft, ohne Muster nie (die echten Arten tragen vorerst keine, #84). Der Name-Treffer für den Aussteller ersetzt die Vorbelegung „zuletzt für die Dokumentart verwendet“ (`default` des Felds); ist er mehrdeutig, gilt weiter diese. Das Formular zeigt „aus Name“ am Feld, bis der Nutzer es ändert (`belege.js`).

**Stand des Baus (Belege, [#75](https://github.com/oiff2/MoarCoal/issues/75)):** Reiter Erwartet unter `/belege/erwartet` (`expected_documents_pages.py`, Vorlage `expected_documents/`): die bisherige Seite samt Anlegen, Ändern (`/belege/erwartet/{id}`) und Löschen; alte Adressen `/erwartete-belege…` leiten mit 308 um, der eigene Navigationseintrag entfällt. Stand je Jahr ausstehend oder erfüllt (kein zweiter Maßstab: `statuses`; ob ein Bezugszeitraum das Jahr berührt, sagt allein `Document.touches_year`); der erfüllende Stand verlinkt auf das Dokument. Hinweise von einer offenen Datei auf einen ausstehenden Erwarteten Beleg (und umgekehrt) gibt es nicht: sie hingen an der Dokumentart aus dem Namen, die echte Arten seit [#84](https://github.com/oiff2/MoarCoal/issues/84) nicht mehr liefern, und sind mit [#94](https://github.com/oiff2/MoarCoal/issues/94) gestrichen; sie können später etwa über den Aussteller wiederkommen. „Ausgenommen“ gibt es erst mit den Ausnahmen des Erwarteten Belegs (nicht gebaut).

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
- Aufteilung ([Prototyp #62](https://github.com/oiff2/MoarCoal/issues/62)): schmale Kopfleiste und linke Seitenleiste um einen scrollenden Inhaltsbereich. Ziel ist ein Desktop ab UWHD bis 4k, Schriftgröße 15 px.
  - Seitenleiste: die angemeldeten Module als Einträge mit Icon (größer als der Text) und Name, in Kategorien gegliedert (Bereiche = Module mit eigener Fachlichkeit, Allgemein = Belege, Aussteller), mit Zähler am Eintrag, wo etwas offen ist. Stufenlos ziehbar (Muss-Anforderung): schmal nur Icons, breit mit Text; `[` klappt um. Die Breite merkt sich der Browser, kein Eintrag der Datenebene. Befunde sind kein Eintrag der Seitenleiste.
  - Kopfleiste: links das Jahr (global, je Seite übersteuerbar), daneben die Befundübersicht des gewählten Jahrs (Zähler je Schweregrad mit Text und dem wichtigsten Befund als Zeile, Link zur Befundliste); rechts oben das Nutzer-Symbol mit Menü (Nutzerwechsel, Hell/Dunkel, Module ein- und ausschalten).
  - Gemeinsame Statussprache: Schweregrad und Belegstand haben je ein festes Symbol und eine feste Farbe, einmal als Jinja-Baustein, nicht je Seite.
  - **Belege-Seite** ([#63](https://github.com/oiff2/MoarCoal/issues/63)): eine Seite `/belege` mit drei Reitern, im Eintrag „Belege“ der Seitenleiste mit Zähler der offenen Dateien; sie löst `/eingang` ab (Weiterleitung), der Befund „n Dateien im Eingang“ führt in die Ablage.
    - **Ablage:** die Ablageorte als einklappbarer Baum, eine Zeile je Datei mit Name, Größe und Stand (offen, aufgenommen), bei aufgenommenen dazu Aussteller, Art und Jahr; Ordner zeigen die Zahl der offenen Dateien. Filter offen / aufgenommen / alle, voreingestellt offen (das ist der **Eingang**). Gleicher Inhalt an mehreren Stellen bleibt eine Zeile. Ausgeblendete stehen nicht im Baum, sondern in einem einklappbaren, flachen Abschnitt „Ausgeblendet (n)“ darunter, denn die Ausblendung hängt am SHA-256 und die Datei kann fehlen; er zählt nirgends und seine Zeilen sind die des Baums (Name, Größe, Stand), anklickbar mit Vorschau rechts; der Kopf zeigt statt Aufnehmen und Ausblenden die Notiz und „Wieder einblenden“ (angepasst durch [#89](https://github.com/oiff2/MoarCoal/issues/89)). Fehlt die Datei, bleibt „keine Vorschau“ und die Größe fehlt.
    - **Vorschau rechts:** Datei anklicken, rechts steht die Vorschau, darüber der Kopf: bei einer offenen Datei das Formular (Aussteller, Dokumentart, Jahr; Aufnehmen, Ausblenden), bei einem Dokument sein Kopf (Aussteller, Ändern, Vorschlag bestätigen, Auslesen). Kopf und Vorschau scrollen jeweils in sich, der Kopf hat eine feste Höhe (45 % der rechten Spalte), kein Seiten-Scrollen; der Link „Dokument“ je Zeile entfällt in beiden Reitern (angepasst durch [#89](https://github.com/oiff2/MoarCoal/issues/89)). Nach Aufnehmen oder Ausblenden springt die Liste zur nächsten offenen Datei (Pfeiltasten, Enter). Keine Mehrfachauswahl. PDF und Bild eingebettet, HTML im Iframe mit `sandbox` ohne Skript, sonst „keine Vorschau“. Zwei Datei-Routen (`/belege/datei/{sha256}` für die Ablage, `/dokumente/{id}/datei`) über `Store.read_site_file` mit dessen Pfadregeln, mit `nosniff`. Der Sprung zur Fundstelle (Seite, markierte Stelle) ist eine spätere Slice.
    - **Dokumente:** alle aufgenommenen Dokumente mit Filter (Art, Jahr, Aussteller, Zustand) und Textsuche; angezeigt wird ein abgeleiteter Zustand („zu bestätigen“, „auszulesen“, „fertig“; ohne Art „Beleg“), gespeichert wird er nicht (angepasst durch [#98](https://github.com/oiff2/MoarCoal/issues/98)). Ändern im selben Formular wie beim Aufnehmen: Aussteller jederzeit, Art und Jahr nur, solange nichts Eingelesenes oder Bestätigtes daran hängt; sonst löschen und neu aufnehmen. Löschen nimmt nur das Dokument weg (die Datei bleibt, wird wieder offen) und nur ohne Verweise von Einzelposten oder Einträgen. Die Details eines Dokuments gibt es nur hier: jeder Link auf ein Dokument zeigt auf `/belege/dokumente?dokument=ID`, Abweisungen beim Ändern, Löschen, Auslesen und Bestätigen zeigen diesen Reiter mit den Gründen, `/dokumente/{id}` leitet mit 308 hierher um (angepasst durch [#95](https://github.com/oiff2/MoarCoal/issues/95)).
    - **Erwartet:** die Erwarteten Belege, je Zeitraum mit Stand erfüllt, fällig oder ausgenommen; verlinkt mit dem erfüllenden Dokument. Keine Platzhalter-Zeilen im Baum.
    - **Vorbelegen aus dem Namen:** feste Regeln, kein Claude, bei jeder Anfrage berechnet, nichts gespeichert, im Formular als „aus Name“ erkennbar und überschreibbar: Aussteller aus Name oder Alias im Datei- oder Ordnernamen, Jahr aus einer Jahreszahl oder einem Datum, Art aus Namensmustern, die eine Dokumentart in der Modulanmeldung mitgeben darf. Aufgenommen wird nie von selbst.
    - **Dokumentarten:** die Datenebene führt keine konkrete; ein Modul meldet eine an, nur wo es etwas damit tut (Einlesen, Auslesen, Bezugszeitraum, Erwarteter Beleg). Ein Dokument ohne Art heißt in der Oberfläche „Beleg“, kein Mangel. Der Bezug eines Werts zu seinem Beleg entsteht im Modul über die Fundstelle; eine eigene Zuordnung am Dokument ist nicht Teil dieser Runde.
    - **Slices:** (1) Gerüst: Eintrag, Reiter, Ablage als Baum mit Ausgeblendet; (2) Vorschau, Datei-Routen, Formular fix, weiter zur nächsten (davor Aussteller-Slices 1 und 2); (3) Dokumente mit Filter, Ändern, Löschen; (4) Erwartet mit Verlinkung; (5) Vorbelegen aus dem Namen. Später: Sprung zur Fundstelle, Rückwärts-Suche (wer stützt sich auf ein Dokument; eigene Slice), manuelle Zuordnung.
  - Bewusst nicht gebaut: Karten-Rahmen, Schiene mit Unterleiste (erst sinnvoll, wenn Module viele Unterseiten haben), Befehlsleiste (`Strg+K`, kein Nutzen, solange es wenige Seiten gibt; bleibt als Idee).

## 7. Claude-Aufruf

Quellen: [Claude als Baustein](https://github.com/oiff2/MoarCoal/issues/7), [ADR 0007](adr/0007-absicherung-server-und-claude-aufruf.md).

- Ein einziger Aufrufbaustein hinter der Auslese-Schnittstelle der Datenebene; in Tests ein Fake.
- `claude -p --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --input-format stream-json --output-format stream-json --verbose` in einem leeren Wegwerfverzeichnis; Abbruch mit Fehler-Befund, wenn `init` Werkzeuge oder MCP-Server meldet. Ein Test prüft die Argumentliste.
- Dokument als base64-`document`- bzw. `image`-Block; Antwort gegen das JSON-Schema aus der Auslese-Vorlage, dann Pydantic; fremde Felder verworfen. Ergebnis ist immer ein Vorschlag.
- Gebaut in `extraction.py`: `Extractor`-Protokoll, `ClaudeExtractor` (echt) und `FakeExtractor`; Fehler (Abbruch, Zeitüberschreitung, ungültige Antwort, nicht unterstütztes Format) kommen als `ExtractionFailed` zurück, nicht als Ausnahme. Die Antwort ist ein JSON-Objekt, dessen Schlüssel die Felder der Vorlage sind, je Feld `value` und `location`.

## 8. Datenschutz

Quelle: [Sensible Werte](https://github.com/oiff2/MoarCoal/issues/14).

- Felder werden am Pydantic-Modell als `Sensitive[str]` markiert, einmal je Feldtyp. Bei Ausstellern nur, wenn sie Privatperson sind.
- Die Datenebene schreibt daraus `common/derived-denylist.txt`: ganze Werte ab 6 Zeichen, bei Namen und Anschriften zusätzlich Teile ab 6 Zeichen. `tools/privacy_guard.py` liest sie neben der handgepflegten Sperrliste, ohne Modelle zu importieren; fehlt sie, gilt nur die handgepflegte, ohne Fehler.
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
- Wie eine Änderung die Ausnahme eines Erwarteten Belegs nennt: über den Erwarteten Beleg oder als eigener Eintrag. Für Ausblendung und Vorschlag hat der Bau entschieden (Abschnitt 2): beide sind Einträge mit eigener Adresse, die auf ihren Eintrag verweisen.

## 12. Außerhalb

Siehe Abschnitt „Out of scope“ der [Karte](https://github.com/oiff2/MoarCoal/issues/1): Übernahme der Kohlebau-Daten, Inhalte der Module (je eigene Karte), Plugin-Laufzeit, Versionierung der Eingaben, Tooltips je Begriff, gemeinsames Eigentum mehrerer Nutzer.
