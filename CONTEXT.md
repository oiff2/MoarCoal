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
Worauf sich ein Einzelposten stützt: eine Stelle in einem Beleg (Seite/Zeile), ein eDaten-Satz aus Mein ELSTER, eine Nutzereingabe mit Datum oder ein anderer Ausgewiesener Wert (dann erbt der Einzelposten dessen Betrag und schwächsten Belegstand).
_Avoid_: Referenz, Quelle (die Fundstelle ist die genaue Stelle, die Quelle der Kanal)

**Quelle**:
Der Kanal, über den Daten von außen in MoarCoal gelangen: eDaten-Abruf aus Mein ELSTER, Dokumentauslesung (von Claude ausgelesen und bestätigt, z. B. Bank-PDF, Bescheid), Übertragungsprotokoll oder Nutzereingabe; alles, was von außen kommt, hat genau eine Quelle.
_Avoid_: Herkunft, Import, Datenquelle

**Belegstand** _(geprägt)_:
Ob ein Einzelposten durch einen Beleg gedeckt ist: belegt (Beleg liegt vor), ausstehend (Beleg wird noch kommen, Betrag gilt bis dahin) oder angenommen (kein Beleg zu erwarten, Betrag ist eigene Annahme oder Rechnung). Stützt sich ein Einzelposten auf einen anderen Ausgewiesenen Wert, erbt er dessen schwächsten Belegstand.
_Avoid_: Gewissheit, Status, geschätzt, erwartet, geplant, vorläufig

**Bezugsobjekt** _(geprägt)_:
Das Ding, auf das sich ein Ausgewiesener Wert bezieht (z. B. eine Immobilie), mit stabiler Kennung und Anzeigenamen.
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

**Notiz**:
Ein freier Text eines Nutzers mit Datum, der an einen beliebigen Eintrag in MoarCoal gehängt werden kann (z. B. Beleg, Einzelposten, Bezugsobjekt), etwa um eine Abweichung zu erklären.
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

**Vertrag**:
Eine laufende Vereinbarung eines Nutzers mit einem Aussteller als Vertragspartner (z. B. Versicherung, Darlehen, Mietvertrag, Strom) mit Vertragsnummer und Laufzeit, der Dokumente zugeordnet werden; was der Vertrag fachlich bedeutet, weiß das Modul.
_Avoid_: Police, Konto, Abo; für die Vereinbarung zwischen Schnittstellen heißt es Contract

**sensibel**:
Eigenschaft eines Felds (nicht eines einzelnen Werts): sein Inhalt sind echte persönliche Daten (z. B. Name, Anschrift, Vertragsnummer) und darf nicht in git, auf GitHub oder ins Protokoll gelangen; an Claude darf er auf Anforderung des Nutzers gehen.
_Avoid_: geheim, vertraulich, privat

**Sperrliste**:
Die Werte, die die Datenschutz-Prüfung vor git und GitHub abfängt: von Hand gepflegt oder aus den sensiblen Feldern der gespeicherten Daten abgeleitet.
_Avoid_: Denylist, Blacklist, Filterliste
