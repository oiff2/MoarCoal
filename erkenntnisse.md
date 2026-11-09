# Erkenntnisse aus Kohlebau

Rückblick zum Projektende (November 2026): Was die App sein und können muss, was sich bewährt hat und was beim nächsten Anlauf anders laufen sollte. Grundlage sind `CONTEXT.md`, die ADRs in `docs/adr/`, das GUI-Glossar, die Recherchen und die offenen Issues.

## 1. Was die App eigentlich ist

- **Die Erklärung tippst du selbst in Mein ELSTER.** Die App bereitet vor und kontrolliert. Sie ersetzt ELSTER nicht.
- **Am meisten bringen zwei Abgleiche:**
  - Das **Übertragungsprotokoll** zeigt Tippfehler beim Übertragen nach ELSTER.
  - Der **EStBescheid** zeigt, wo das Finanzamt anders gerechnet hat.
  - Der Jahresvergleich mit dem Vorjahr kommt an dritter Stelle.
- **Die Einheit ist die Zeile einer Anlage.** Jeder Wert stammt von genau einem Aussteller und gehört zu genau einer Zeile. Der Wert einer Zeile ist die Summe ihrer Einträge.
- **Kennzahlen taugen nicht als Schlüssel.**
  - Sie gelten nur innerhalb einer Anlage. Auf dem Papier wird sogar pro Seite gezählt: Anlage N 2025 hat zweimal Kz 110.
  - Manche Felder haben gar keine Kennzahl. Verlässlich ist die **E-Kennung** (E + 7 Ziffern), und die erfährt man erst aus dem Übertragungsprotokoll.
  - Auch die Zeilennummern wechseln von Jahr zu Jahr. Man braucht also einen Katalog pro Jahr und eine strikte Zuordnung zum Vorjahr (`vorjahr`, ADR 0002).
- **Gerundet wird zugunsten des Steuerzahlers, je nach Richtung** (Einnahme ab-, Ausgabe aufrunden).
  - Listenzeilen wie Vorsorgeaufwand werden pro Einzelangabe gerundet.
  - Der Bescheid druckt viele Beträge in ganzen Euro, auch wo das Feld Cent hat. Abgleiche brauchen deshalb Spannen statt Einzelwerte (ADR 0011).
- **eDaten gibt es nur zum Nachprüfen.** Was im Vordruck mit „e“ markiert ist, kennt das Finanzamt schon. Alles andere musst du eintippen.
- **Berechnen statt speichern hat sich bewährt:** Befunde, Review, AfA, Tilgungsplan. Der Preis dafür: Nach der Abgabe darf sich nichts mehr ändern, was in eine schon abgegebene Erklärung einfließt. Das prüft man am besten **an einer Stelle beim Speichern**, nicht in jeder einzelnen Route. ADR 0044 hat 34 verstreute Prüfungen durch eine einzige ersetzt.

## 2. Woher die Daten kommen

| Quelle | Wie | Besonderheit |
|---|---|---|
| eDaten (Lohnsteuerbescheinigung, Versicherungen, Freistellungsaufträge) | HTML-Download aus „Meine Bescheinigungen“, genau einlesbar | Mein ELSTER bietet keinen anderen Export. Maschinell ginge es nur über ERiC, und dafür braucht man eine eigene Hersteller-ID. Die Daten liegen ab Ende Februar vor, für die letzten 4 Jahre. |
| Bank-PDFs, Versicherungs-PDFs | Claude liest einen Vorschlag aus, du bestätigst | Bescheinigungen drucken ihre Ziel-Zeile mit („Zeile 7 Anlage KAP“). Verschlüsselte PDFs liest man über `pdftotext`. |
| Übertragungsprotokoll (HTML) | genau einlesbar | Quelle der E-Kennungen. Es belegt nichts und erzeugt keine Einträge. |
| EStBescheid (PDF) | Claude liest die Positionen aus | Doppelt gedruckte Bezeichnungen brauchen ihren Block in Klammern. |
| Vordrucke und Anleitungen | formulare-bfinv.de, per HTTP mit Session-Cookie | Änderungen gegenüber dem Vorjahr sind in der Anleitung grün gedruckt. Bis 2018 liegen sie in einem Archivordner. |
| Eigenbelege | Dienstreisen (Screenshots, die Claude ausliest), Fahrten zur Immobilie | Es gibt keine andere Quelle, also gehört eine Notiz oder ein Nachweis dazu. |
| Immobilie | Kaufvertrag, Darlehensvertrag, Zahlungsanforderungen | Das sind **Unterlagen**, keine Belege. Sie gehören zu keinem Steuerjahr. |
| Vorjahr | Übernahme | Am meisten bringt sie als **Erwartete Belege** mit Bezugsweg und Bezugshinweis. Die Werte selbst müssen ohnehin neu kommen. |

## 3. Wie man die Daten organisiert

- **Belege bleiben, wo sie sind.** Sie behalten ihren Originalnamen und werden über Pfad und SHA-256 erkannt. Nichts wird umbenannt oder überschrieben.
- **Eigene Dateien der App liegen versteckt in `<jahr>/.kohlebau/`.** Sonst tauchen sie in der Belegliste auf.
- **Ein Aussteller behält seine id für immer.** Dubletten führt man zusammen, indem die alte id beim Laden umgeleitet wird. Alte Jahre werden dafür nie umgeschrieben.
- **Ein Erwarteter Beleg ist eindeutig durch Aussteller, Belegtyp, Bezeichnung (also den Vertrag) und die Immobilie.** Ohne die Bezeichnung lassen sich zwei Verträge bei derselben Bank nicht unterscheiden.
- **Eine Immobilie gehört zu keinem Jahr.** Sie bekommt eine eigene Datei, und in jedem Jahr, in dem du sie hältst, eine eigene Anlage V.
- **Persönliche Daten kommen nie ins Repo.** Die Sperrliste im Commit-Hook hat sich bewährt.

## 4. Sprache und Tooltips

- **Vier Textebenen, sauber getrennt:**
  1. die **Beschriftung** der Zeile wörtlich wie im Vordruck, damit du sie in ELSTER wiederfindest;
  2. eine **ausgeschriebene Beschriftung** für Bruchstücke wie „aufgesucht an Tagen“;
  3. eine **Erläuterung je Zeile** (1–3 Sätze in Du-Form, nur bei Fallen oder Rechenregeln);
  4. ein **Tooltip je Begriff**: gilt für alle Jahre, nennt keine Beträge und verlinkt auf andere Begriffe.

  Technische Schlüssel stehen nur in der Kurzinfo (dem `title=` des Browsers).
- **Ein Verb pro Handlung:** hochladen, aufnehmen, auslesen (Claude), einlesen (exakt, ohne Claude), übernehmen.
- **Befunde nach Art benennen:** „2 Abweichungen, 1 Hinweis“, nicht „3 Befunde“. Die Zahlen der App heißen „Deine Einträge“.
- **Herkunft farbig wie in ELSTER markieren:** eDaten, aus PDF, aus dem Vorjahr, berechnet, von Hand.
- **Die Lehre daraus:** Es wurden zu viele eigene Begriffe erfunden (Spiegel, Teilseite, Ausprägung, Hilfsübersicht, Auswertung …). `CONTEXT.md` ist auf 360 Zeilen gewachsen, und #76 musste hinterher aufräumen. Beim nächsten Mal zuerst die Wörter aus ELSTER und aus dem Alltag nehmen und nur dort einen Begriff prägen, wo es wirklich keinen gibt.

## 5. Anlage V (Neubau-Eigentumswohnung vom Bauträger)

Die Quellen und der Stand „fest / abgeleitet / offen“ stehen in `docs/recherche-anlage-v-afa-neubau.md` und `docs/recherche-disagio-anlage-v.md`.

**Zeitraum und Stammdaten**
- Anlage V gibt es ab dem Jahr des Kaufvertrags bis zum Jahr des Verkaufs.
- Der **Eigentumsübergang (Z. 7) ist die Übergabe** (Besitz, Nutzen und Lasten gehen über). Er ist nicht die Abnahme und nicht der Grundbucheintrag. Mit der Übergabe beginnt auch die AfA.

**Bauphase**
- Kosten vor der ersten Miete sind vorab entstandene Werbungskosten, wenn die Vermietungsabsicht belegbar ist. Belege dafür sind etwa der Beitritt zum Mietpool oder eine langfristige Finanzierung.
- Sollzinsen und Bereitstellungszinsen zählen beide als Schuldzinsen.

**Schuldzinsen**
- Der **Jahreskontoauszug der Bank hat Vorrang.** Die erfassten Zinszahlungen sind nur vorläufig und dienen zur Gegenprobe.
- Die Zehn-Tage-Regel (§ 11 EStG) lässt sich nur anwenden, wenn die Buchungen datiert sind.

**Kaufnebenkosten**
- Jede Kostenposition ist entweder Anschaffungskosten oder sofort abziehbare Werbungskosten. Beispiel: Der Notar für den Kaufvertrag zählt zu den Anschaffungskosten, der Notar für die Grundschuld zu den Werbungskosten.
- Grunderwerbsteuer fällt nicht auf die Einbauküche an.
- Ein Disagio geht in Z. 46–48, Bearbeitungsgebühren als Geldbeschaffungskosten in Z. 49–51. Beide sind sofort abziehbar, wenn die Zinsbindung mindestens 5 Jahre läuft und der Betrag höchstens 5 % ausmacht.

**Kaufpreisaufteilung**
- Gebäude, Grund und Boden, Inventar. Nur Gebäude und Inventar werden abgeschrieben.

**AfA**
- **Gebäude:** degressiv 5 % vom Restwert (§ 7 Abs. 5a), im ersten Jahr anteilig nach Monaten. Einmal ist ein Wechsel zu linear möglich, zurück geht es nicht. Jeder Jahresbetrag wird auf volle Euro aufgerundet.
- **Sonder-AfA § 7b:**
  - 4 Jahre lang je 5 %, schon im ersten Jahr voll.
  - Bemessungsgrundlage höchstens 4.000 €/m². Liegen die Baukosten über 5.200 €/m², entfällt sie ganz.
  - In den Jahren 1–4 mindert sie die Basis der degressiven AfA nicht (BMF, Beispiel 7 c).
  - Überschreiten nachträgliche Kosten die Obergrenze, entfällt die Sonder-AfA rückwirkend für alle Jahre.
- **Einbauküche:** ein eigenes Wirtschaftsgut, 10 Jahre linear.
- **Nachträgliche Anschaffungskosten** zählen so, als wären sie zu Beginn ihres Jahres angefallen (R 7.4 Abs. 9 EStR).

**Mietpool und Hausgeld**
- Nicht nur die Auszahlung eintragen, sondern aufteilen:
  - Einnahmen in Z. 13;
  - Umlagen in Z. 20;
  - Saldo aus Nachzahlung und Erstattung in Z. 21;
  - umgelegte Kosten in Z. 73;
  - nicht umgelegte Kosten plus Pool- und Verwaltergebühr in Z. 76;
  - Entnahmen in Z. 55.
- Die **Zuführung zur Erhaltungsrücklage ist keine Werbungskosten** (BFH IX R 19/24).
- Noch offen: ob der Pool eine eigene Feststellung nach § 180 AO auslöst, und wann die Mieten als zugeflossen gelten.

**Sonstiges**
- Die Grundsteuer steht in einem Dauerbescheid. Läuft sie über das Hausgeld, darf sie nicht doppelt zählen.
- Fahrten zur Immobilie gehören in Z. 80–82, nicht in Anlage N.
- Eine Kontoführungspauschale gibt es bei Vermietung nicht.

**Praxis**
- Viele Felder der Anlage V haben keine bekannte E-Kennung, bis ein Übertragungsprotokoll sie zeigt. Bis dahin dient die gedruckte Kennzahl als Schlüssel.
- Die Recherche nach Primärquellen mit der Markierung „fest / abgeleitet / offen“ hat sich bewährt. Die Erstfassung hatte trotzdem 17 Korrekturen, eine unabhängige zweite Prüfung lohnt sich.

## 6. Dashboards, Zinspläne, Prognose

- **Unbekannt zeigt „–“, nie 0.** Eine Summe zählt nur, was bekannt ist.
- **Ist schlägt Plan:** Wo ein Jahresstand der Bank vorliegt, gilt er. Sonst gilt der Tilgungsplan, und jedes Planjahr wird als bestätigt, gesichert oder angenommen markiert.
- **Die Prognose steht optisch abgesetzt.** Platzhalter wie die Nettomiete sind markiert.
- **Es wird nie eine Steuerersparnis gezeigt**, nur das Ergebnis aus Vermietung und Verpachtung. Für die Einschätzung von Claude gilt dieselbe Grenze.
- **Spalten sind eine Liste im Code**, die Vorlage zeichnet, was darin steht. So ließ sich alles leicht erweitern.
- **Fristen werden aus den Daten berechnet**, jeweils mit ihrer Rechtsgrundlage. Eigene Fristen sind die bewusste Ausnahme.
- **Die Lehre daraus:** Diese Ansichten sind Ticket für Ticket entstanden und jetzt über Startseite, Immobilienseite, Übersicht und Review verstreut. Besser wäre ein eigener Bereich „Immobilie“ mit festen Reitern (Stammdaten · Finanzierung · Kauf & AfA · Jahre · Verlauf/Prognose), klar getrennt von der Seite der Erklärung.

## 7. Was gut war und bleiben sollte

**Betrieb und Oberfläche**
- **Ein lokaler Webserver, jede Seite eine URL.** Kein Login, kein Build-Schritt, kein npm. Man kann Seiten verlinken, in Tabs öffnen und mit der Zurück-Taste arbeiten. Gestartet wird per Windows-Verknüpfung, und der Server beendet sich von selbst, wenn keine Seite mehr offen ist.
- **Die Dienstreisen-Seite ist der beste Prototyp der App:**
  - eine Tabelle, die man komplett mit der Tastatur bedient;
  - Screenshots, die Claude ausliest;
  - eine Karte, deren Ortssuche erst auf Klick etwas sendet;
  - am Ende die Bestätigung „vollständig“.

  Daraus lässt sich das Muster für jede Erfassungsseite ableiten: kompakt, schnell, mit sofort sichtbarem Ergebnis.
- **Hell- und Dunkelmodus** über CSS-Variablen; Karte und Diagramme folgen ohne zweite Datei.
- **Fundstelle mit einem Klick:** Ein Wert springt zu seiner Stelle im Beleg, mit der Seite im PDF oder der markierten Stelle im eDaten-HTML. Jede Zahl bleibt nachvollziehbar.
- **Die Review führt zur Stelle und zurück:** „zur Stelle ›“ und „‹ zurück zur Review“.
- **Die Detailspalte** zeigt rechts Beleg, Notizen und Jahresvergleich neben der Zeile, ohne Seitenwechsel.

**Arbeitsweise mit Daten**
- **Claude macht Vorschläge, du bestätigst.** Nichts wird still überschrieben, und die Herkunft jedes Werts ist sichtbar.
- **Nichts blockiert, nichts muss quittiert werden.** Befunde werden bei jeder Anzeige neu berechnet. Eine Erklärung schreibst du in eine Notiz. Das hält die Reibung niedrig.
- **Neu laden zeigt immer den aktuellen Stand** von der Platte, ohne veralteten Zustand.
- **Lesbare JSON-Dateien** mit Sicherung vor jedem Schreiben in `.backup/`. Daten lassen sich zur Not von Hand reparieren.
- **Erwartete Belege als Jahres-Checkliste:** Bezugsweg und Bezugshinweis wandern mit ins nächste Jahr.

**Technik**
- **Beträge als ganze Cent oder `Decimal`**, nie als Gleitkommazahl.
- **Strenger Katalog:** unbekannte Schlüssel und doppelte Einträge werden abgelehnt, und eine vergessene Vorjahres-Zuordnung lässt einen Test fehlschlagen, statt still zu verschwinden.
- **Claude über `claude -p` mit dem Pro-Abo, ohne API-Key.** Alles Externe sitzt hinter einer Schnittstelle (Claude, formulare-bfinv.de, Ortssuche), Tests laufen mit Fakes ohne Netz.
- **Schneller Testkern (~5 s) vor jedem Commit**, voller Lauf vor jedem Push.
- **Datenschutz durchgehalten:** alles lokal, keine automatische Geocodierung, Sperrliste im Commit-Hook.
- **`CONTEXT.md` und ADRs** haben Agents und Menschen dieselben Begriffe und Entscheidungen gegeben, auch wenn der Umfang zu groß wurde.
- **Der Skill `katalog-pruefen` und der Vordruck-Download** machen den jährlichen Katalog zu einer überschaubaren Aufgabe.

## 8. Warum es zum Frankenstein wurde

- **Gewachsen Ticket für Ticket**, mit nachträglichen Ergänzungen an den ADRs. Am Ende sind es 44 ADRs und rund 28.000 Zeilen Python.
- **Die Navigation spiegelt ELSTER als Baum.** Die „Tools“ wurden daneben angeflanscht.
- **Die Immobilien kamen spät** auf ein Modell, das um das einzelne Steuerjahr gebaut war: Immobilie als Teil des Schlüssels, jahresübergreifende Hilfsübersichten.
- **Die Sperre nach der Abgabe wurde nachgerüstet.**

**Für einen Neustart:**
1. von den Abläufen ausgehen: Belege sammeln → Werte prüfen → Übertragung kontrollieren → Bescheid prüfen;
2. von Anfang an zwei Bereiche vorsehen: Steuerjahr und Immobilie;
3. einen schlanken Wortschatz pflegen;
4. den fachlichen Kern als reine Funktionen bauen und die Oberfläche zuletzt;
5. jede Erfassungsseite nach dem Muster der Dienstreisen-Seite bauen.
