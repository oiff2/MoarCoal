# MoarCoal

Persönliche Finanzverwaltung, in der Belege, Steuererklärung, Immobilien und weitere Themen zusammenlaufen.

## Language

**Datenebene** _(geprägt)_:
Der gemeinsame Unterbau: gespeicherte Daten und die Fachbausteine, die alle Module gleich brauchen (Geldbetrag, Zeitraum, Quelle, Schnappschuss).
_Avoid_: Datalayer, Kern, Backend, Datenbank

**Modul**:
Ein Themenblock (z. B. Steuerjahr, Immobilie), der auf der Datenebene aufbaut und von anderen Modulen nur deren Ausgewiesene Werte liest.
_Avoid_: Plugin, Tool, Feature

**Modulanmeldung** _(geprägt)_:
Was ein Modul beim Start der App über sich bekannt gibt: seine Schlüssel im Wertekatalog, seine Datenstrukturen, seine Auslese-Vorlagen und seine Seiten in der Oberfläche (Code: `ModuleRegistration`).
_Avoid_: Registry, Manifest, Plugin-Deklaration; „Anmeldung“ allein (klingt nach Login eines Nutzers)

**Befund** _(geprägt)_:
Ein Punkt, der die Aufmerksamkeit eines Nutzers verdient (z. B. ausstehender Beleg, Abweichung zum Schnappschuss, auslaufender Vertrag), mit Schweregrad (Hinweis, Warnung, Fehler) und Verweis auf den betroffenen Eintrag in MoarCoal (z. B. Beleg, Einzelposten, Vertrag, Bezugsobjekt).
Befunde werden auf Anfrage aus dem aktuellen Stand berechnet und verschwinden, sobald ihre Ursache behoben ist; ein Nutzer kann einen Befund mit Notiz ausblenden, bis sich der zugrunde liegende Stand ändert.
_Avoid_: Issue, Problem, Warnung oder Fehler (allein, das sind Schweregrade), quittieren, erledigen

**Befundliste** _(geprägt)_:
Die eine Stelle, an der alle offenen Befunde eines Nutzers über alle Module hinweg gesammelt werden.
_Avoid_: Review, Inbox, To-do, Durchsicht

**Nutzer**:
Eine Person mit eigenen Daten, Belegen und Steuererklärungen; mehrere Nutzer sind möglich, ihre Daten bleiben getrennt.
_Avoid_: Account, Profil, Steuerpflichtiger

**Ausgewiesener Wert** _(geprägt)_:
Das Ergebnis einer Berechnung über Einzelposten, das ein Modul über die Datenebene für andere Module ausweist (Code: `ExposedValue`); er kann selbst in weitere Berechnungen eingehen. Wie gerechnet wird, legt das Modul fest und hält es im Rechenweg fest. Fehlt eine Eingabe, regelt entweder die Rechnung des Moduls ausdrücklich, wie damit umzugehen ist, oder der Wert ist **noch nicht berechenbar**, ebenso jeder Wert, der auf ihm aufbaut; nie eine stille Null.
_Avoid_: Veröffentlichter Wert, Export, Schnittstelle, Wert (allein), Kennzahl (in ELSTER die Feldnummer), Kennwert

**Einzelposten** _(geprägt)_:
Eine Eingabe in die Berechnung eines Ausgewiesenen Werts, mit eigener Einheit, Fundstelle und Belegstand; die Quelle ergibt sich aus der Fundstelle.
_Avoid_: Position, Zeile, Buchung

**Rechenweg**:
Die festgehaltene Folge der Schritte, mit der ein Modul einen Ausgewiesenen Wert berechnet hat: Eingänge, Zwischenergebnisse und Entscheidungen; für alle Module gleich dargestellt und im Schnappschuss mit eingefroren.
_Avoid_: Formel, Herleitung, Trace

**Fundstelle** _(geprägt)_:
Worauf sich ein Einzelposten stützt: eine Stelle in einem Beleg (Seite/Zeile), ein eDaten-Satz aus Mein ELSTER, ein Erwarteter Beleg, eine Nutzereingabe (ein Eintrag des Moduls, genannt über seine Adresse) oder ein anderer Ausgewiesener Wert (dann erbt der Einzelposten dessen Betrag und schwächsten Belegstand). Aus der Art der Fundstelle ergibt sich der Belegstand.
_Avoid_: Referenz, Quelle (die Fundstelle ist die genaue Stelle, die Quelle der Kanal)

**Quelle**:
Der Kanal, über den Daten von außen in MoarCoal gelangen: eDaten-Abruf aus Mein ELSTER, Dokumentauslesung (von Claude ausgelesen und bestätigt, z. B. Bank-PDF, Bescheid), Übertragungsprotokoll oder Nutzereingabe; alles, was von außen kommt, hat genau eine Quelle.
_Avoid_: Herkunft, Import, Datenquelle

**Belegstand** _(geprägt)_:
Ob ein Einzelposten durch einen Beleg gedeckt ist; er ergibt sich aus der Art der Fundstelle: belegt (Fundstelle ist ein Beleg oder ein eDaten-Satz), ausstehend (Fundstelle ist ein Erwarteter Beleg, der Betrag gilt, bis der Beleg da ist) oder angenommen (Fundstelle ist eine Nutzereingabe, kein Beleg zu erwarten). Stützt sich ein Einzelposten auf einen anderen Ausgewiesenen Wert, erbt er dessen schwächsten Belegstand.
_Avoid_: Gewissheit, Status, geschätzt, erwartet, geplant, vorläufig

**Bezugsobjekt** _(geprägt)_:
Der Eintrag, auf den sich ein Ausgewiesener Wert bezieht (z. B. eine Immobilie); er gehört dem Modul, das ihn führt, und andere Module kennen von ihm nur Adresse, Anzeigenamen und seine Ausgewiesenen Werte.
_Avoid_: Entität; „Objekt“ nur im Immobilienmodul für die Immobilie selbst

**Zeitraum**:
Ein Intervall von Tagen, für das ein Zeitraumwert gilt, meist ein Kalenderjahr.
_Avoid_: Periode, Veranlagungszeitraum (steuerrechtlich enger)

**Stichtagswert** _(geprägt)_:
Ein Ausgewiesener Wert, der für einen Tag gilt (z. B. Restschuld am 31.12.); Stichtagswerte werden nicht über Zeiträume summiert (ihre Einzelposten schon).
_Avoid_: Bestand, Saldo

**Zeitraumwert** _(geprägt)_:
Ein Ausgewiesener Wert, der für einen Zeitraum gilt (meist ein Kalenderjahr, z. B. Mieteinnahmen 2025); Zeitraumwerte lassen sich über Zeiträume summieren.
_Avoid_: Bewegung, Umsatz

**Wertekatalog** _(geprägt)_:
Die Liste aller Schlüssel (stabile fachliche Kennungen) Ausgewiesener Werte, die Module anmelden, mit Bedeutung und Einheit (Code: `ValueCatalog`; Schlüssel: `ValueKey`).
_Avoid_: Registry, Verzeichnis, Katalog (allein)

**Schnappschuss**:
Der zu einem Anlass (z. B. Abgabe einer Steuererklärung) eingefrorene Stand von Ausgewiesenen Werten samt Einzelposten; unveränderlich, hängt nicht vom Ablageort ab, denn die Dokumente, auf die er verweist, werden beim Einfrieren ins Datenverzeichnis kopiert; spätere Abweichungen vom aktuellen Stand werden sichtbar statt verhindert (Code: `Snapshot`; der Vorgang heißt einfrieren).
_Avoid_: Sperre, Abgabestand, Festschreibung, Version

**Aussteller**:
Wer ein Dokument ausgestellt hat (Bank, Versicherung, Finanzamt, Handwerker); geführt in einem eigenen Katalog mit Informationen je Aussteller, auf den Dokumente und Verträge verweisen. Ein Aussteller ist eine Firma oder Behörde, außer er ist als **Privatperson** gekennzeichnet (z. B. privater Vermieter); nur dann sind Name und Anschrift sensibel.
_Avoid_: Absender, Firma, Gegenpartei

**Eintrag**:
Etwas Gespeichertes in MoarCoal mit eigener Adresse, z. B. Dokument, Aussteller, Vertrag, Immobilie, Darlehen, Dienstreise; Ausgewiesene Werte und ihre Einzelposten sind berechnet und keine Einträge.
_Avoid_: Datensatz, Objekt, Entität, Record

**Adresse**:
Wie ein Eintrag überall in MoarCoal genannt wird (in Notizen, Befunden, Fundstellen, Zuordnungen und Links): seine Art, fachlich benannt und über alle Module eindeutig (z. B. Immobilie, Darlehen), plus eine Kennung, die beim Anlegen zufällig vergeben wird und sich nie ändert (Code: `EntryAddress`).
_Avoid_: Referenz, Link, Pfad; für die Postanschrift heißt es Anschrift

**zuordnen**:
Ein Dokument einem anderen Eintrag zuweisen, den es betrifft (z. B. einem Vertrag oder einer Immobilie); die Zuordnung steht am Dokument, egal welchem Modul der andere Eintrag gehört.
_Avoid_: verknüpfen, verlinken, taggen

**Notiz**:
Ein freier Text eines Nutzers mit Datum, der an einen beliebigen Eintrag in MoarCoal gehängt werden kann (z. B. Beleg, Vertrag, Bezugsobjekt), etwa um eine Abweichung zu erklären; nicht an Berechnetes, denn Einzelposten und Ausgewiesene Werte entstehen bei jeder Anfrage neu.
_Avoid_: Kommentar, Anmerkung, Memo

**Dokument**:
Eine Datei, die MoarCoal kennt, ob an einem Ablageort verwiesen oder ins Datenverzeichnis übernommen, (z. B. Rechnung, Kontoauszug, Bescheid, Mietvertrag) mit Quelle, Aussteller und Datum.
_Avoid_: Unterlage, Datei, Anhang

**Datenverzeichnis**:
Der Ordner, in dem MoarCoal seine eigenen Daten hält (`~/MoarCoal/`), getrennt von den Ablageorten der Dokumente.
_Avoid_: Datenordner, Speicherort

**Ablageort** _(geprägt)_:
Ein benannter, für alle Nutzer gemeinsamer Ordner außerhalb des Datenverzeichnisses, in dem Dokumente liegen (z. B. „Belege“, „Scan-Eingang“); MoarCoal liest dort nur und verweist auf Dokumente über Ablageort, relativen Pfad und Prüfsumme.
_Avoid_: externer Ordner, Quellordner, Mount

**Eingang** _(geprägt)_:
Die Liste der Dateien in den Ablageorten, die weder aufgenommen noch ausgeblendet sind; daraus wird nichts von selbst übernommen.
_Avoid_: Inbox, Import, Vorschlag

**aufnehmen**:
Eine Datei aus dem Eingang zum Dokument machen; danach wird sie je nach Art eingelesen oder ausgelesen. Gegenstück: **ausblenden** (die Datei erscheint nicht mehr im Eingang).
_Avoid_: importieren, einlesen (für diesen Schritt)

**auslesen**:
Claude liest Felder aus einem Dokument und legt sie als Vorschlag ab; im Unterschied zu einlesen (exakt, ohne Claude, z. B. Übertragungsprotokoll).
_Avoid_: importieren, extrahieren, parsen

**Vorschlag**:
Das Ergebnis einer Auslesung an einem Dokument: Felder mit Wert und Fundstelle, die erst nach Bestätigung durch den Nutzer (je Feld, ggf. korrigiert) in Daten eines Moduls übergehen; bleibt danach samt Korrekturen erhalten (Code: `Proposal`).
_Avoid_: Entwurf, Vorschlagswert, unbestätigter Einzelposten

**Auslese-Vorlage** _(geprägt)_:
Was ein Modul für eine Dokumentart auslesen lassen will: Liste der Felder mit Einheit und Hinweis für Claude (Code: `ExtractionTemplate`).
_Avoid_: Prompt, Schema, Formular

**Beleg**:
Ein Dokument, das einen Betrag nachweist und als Fundstelle für Einzelposten dient; nicht jedes Dokument ist ein Beleg.
_Avoid_: Quittung, Nachweis

**Erwarteter Beleg**:
Ein Beleg, der regelmäßig oder einmalig kommen soll, z. B. jährlich die Zinsbescheinigung zu einem Darlehen: Aussteller, Dokumentart, die Einträge, die er betrifft, Rhythmus mit Beginn und Ende sowie Bezugsweg und Bezugshinweis. Ein Eintrag mit eigener Adresse, der weiterläuft, bis er endet; für jeden Zeitraum ergibt sich daraus, was zu erwarten ist, ohne Übernahme ins nächste Jahr. Er ist **erfüllt**, sobald ein passendes Dokument da ist; fällt er für einen Zeitraum aus, trägt er dafür eine Ausnahme mit Notiz.
_Avoid_: Checkliste, Erwartung (allein), offener Beleg, Platzhalter

**Dokumentart**:
Was für ein Dokument es ist (z. B. Zinsbescheinigung, Grundsteuerbescheid, Darlehensvertrag); Module melden ihre Dokumentarten an, die Datenebene einige allgemeine. Jedes Dokument hat höchstens eine. Die Dokumentart legt fest, ob ihre Dokumente einen **Bezugszeitraum** haben, den Zeitraum, für den das Dokument gilt (z. B. Zinsbescheinigung 2025, ausgestellt 2026); andere gelten ohne zeitliche Grenze (z. B. Darlehensvertrag).
_Avoid_: Belegtyp, Dokumenttyp, Kategorie

**Bezugsweg**:
Wie ein Erwarteter Beleg zu beschaffen ist, aus einer festen Liste (Post, Online-Postfach des Ausstellers, E-Mail, eDaten aus Mein ELSTER, selbst erstellen); dazu der **Bezugshinweis** als freier, sensibler Text, nie mit Zugangsdaten.
_Avoid_: Kanal, Quelle (die Quelle ist der Weg in MoarCoal, nicht zum Nutzer)

**Vertrag**:
Eine laufende Vereinbarung eines Nutzers mit einem Aussteller als Vertragspartner (z. B. Versicherung, Darlehen, Mietvertrag, Strom) mit Vertragsnummer und Laufzeit, dem Dokumente zugeordnet werden; was der Vertrag fachlich bedeutet, weiß das Modul.
_Avoid_: Police, Konto, Abo; für die Vereinbarung zwischen Schnittstellen heißt es Contract

**sensibel**:
Eigenschaft eines Felds (nicht eines einzelnen Werts): sein Inhalt sind echte persönliche Daten (z. B. Name, Anschrift, Vertragsnummer) und darf nicht in git, auf GitHub oder ins Protokoll gelangen; an Claude darf er auf Anforderung des Nutzers gehen.
_Avoid_: geheim, vertraulich, privat

**Sperrliste**:
Die Werte, die die Datenschutz-Prüfung vor git und GitHub abfängt: von Hand gepflegt oder aus den sensiblen Feldern der gespeicherten Daten abgeleitet.
_Avoid_: Denylist, Blacklist, Filterliste
