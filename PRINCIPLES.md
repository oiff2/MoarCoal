# Architekturprinzipien

Jede Änderung, die gemergt wird, hält diese Prinzipien. Wer eines nur durch einen Bruch einhalten kann, oder findet, dass eines nicht mehr passt, fragt nach, statt es still zu brechen. Begriffe stehen in [`CONTEXT.md`](CONTEXT.md), Einzelheiten in [`docs/grundgeruest.md`](docs/grundgeruest.md) und [`docs/adr/`](docs/adr/).

## 1. Datenebene vs. Modul

**Regel:** Die Datenebene hält gespeicherte Daten und die Bausteine, die alle Module gleich brauchen. Themenlogik gehört ins Modul, Web-Wissen (Routen, URLs, Vorlagen) in die Anbindung.

**Warum:** So bleibt die Datenebene stabil und für jedes Modul nutzbar, und Module lassen sich austauschen, ohne sie anzufassen (grundgeruest §1, §2).

**Verstoß im Diff:** `storage/` oder `values/` importiert aus `modules/` oder aus Seiten-Code, kennt eine Route wie `/belege/…` oder trägt Themenbegriffe eines einzelnen Moduls.

## 2. Module kennen sich nicht

**Regel:** Module verbinden sich nur über Ausgewiesene Werte und über Adressen von Einträgen. Fremde Werte zeigt ein Modul nur über den gemeinsamen Anzeigebaustein.

**Warum:** Jedes Modul bleibt einzeln verständlich, testbar und abschaltbar (grundgeruest §1, §4).

**Verstoß im Diff:** Ein Modul importiert aus einem anderen Modul, bindet dessen Vorlagenteile ein oder liest dessen Einträge direkt.

## 3. Ein Schreibweg, Regeln im Vorgang

**Regel:** Geschrieben wird nur über `apply` der Datenebene. Regeln, die für jeden Schreibweg gelten müssen, prüft der Vorgang (z. B. `EntryKind.check`), nicht die Seite vorher auf einem älteren Stand.

**Warum:** Nur so gelten Prüfsummen, Sicherung, Journal und Prüfungen für jede Änderung, auch für künftige Schreibwege und gleichzeitige Anfragen ([ADR 0006](docs/adr/0006-schreibweg-vorgang-mit-journal.md)).

**Verstoß im Diff:** Direkter Dateizugriff außerhalb der Datenebene, eine Invariante, die nur auf `store.state()` vor `apply` geprüft wird, oder ein zweiter Schreibpfad neben `apply`.

## 4. Reiner Fachkern, dünne Anbindung

**Regel:** Fach- und Schreiblogik sind reine Funktionen: Stand rein, Ergebnis oder Liste von Änderungen raus. Routen lesen das Formular, rufen den Kern auf, übergeben an `apply` und rendern.

**Warum:** Reine Funktionen lassen sich einzeln testen, und Seiten bleiben austauschbar (grundgeruest §4, drei Schichten).

**Verstoß im Diff:** Fachentscheidungen oder Berechnungen im Route-Handler oder in Vorlagen, Datei- oder Netzzugriff im Fachkern.

## 5. Nie eine stille Null

**Regel:** Ein Wert hat einen Betrag, ist noch nicht berechenbar oder entfällt. Fehlendes wird nie zu 0.

**Warum:** Eine Steuererklärung mit stillen Nullen sieht vollständig aus und ist falsch (grundgeruest §1, §3.3).

**Verstoß im Diff:** `or 0`, `default=0`, `sum()` über optionale Beträge ohne Unterscheidung, oder `None`, das als 0 angezeigt wird.

## 6. Glossar zuerst

**Regel:** Jeder Fachbegriff und jeder Typ mit Fachbedeutung steht in `CONTEXT.md` (mit `(Code: Name)`), bevor er in Code oder Oberfläche auftaucht. Neue Begriffe gibt es nur, wo ELSTER, Steuerrecht oder Alltag kein Wort haben. Höchstens 30 geprägte Begriffe.

**Warum:** Das Glossar ist die einzige Zuordnung Deutsch ↔ Englisch, und der Testkern setzt es durch (AGENTS.md „Glossar“, grundgeruest §9).

**Verstoß im Diff:** Ein neuer Typ oder Oberflächenbegriff ohne Glossareintrag, ein Eintrag ohne `Code:`, obwohl es den Typ gibt, oder ein gemiedenes Wort in einer Vorlage.

## 7. Wiederverwenden statt neu schreiben

**Regel:** Vor jedem neuen Baustein, Typ oder jeder Hilfsfunktion prüfen, ob es das schon gibt. Wenn ja, das Vorhandene erweitern. Jede Logik gibt es genau einmal.

**Warum:** Der Code soll nur wachsen, wo er muss. Doppelte Logik läuft auseinander (Notes der Karte #61).

**Verstoß im Diff:** Eine zweite Funktion, die dasselbe tut wie eine bestehende (z. B. Jahres-Parsing an zwei Stellen), ein neuer Baustein neben einem passenden alten, oder kopierte Blöcke.

## 8. Nichts geht nach außen, GET ändert nie

**Regel:** Kein CDN und kein automatischer Netzzugriff. Claude läuft nur über den einen Aufrufbaustein mit fester Argumentliste. GET-Anfragen ändern nie etwas.

**Warum:** Persönliche Finanzdaten bleiben lokal, und die Absicherung gegen fremde Webseiten und eingeschleuste Anweisungen hängt daran ([ADR 0002](docs/adr/0002-technikstack.md), [ADR 0007](docs/adr/0007-absicherung-server-und-claude-aufruf.md)).

**Verstoß im Diff:** Eine externe URL in Vorlage oder Code, ein schreibender GET-Handler oder ein zweiter `claude`-Aufruf.
