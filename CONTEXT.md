# MoarCoal

Persönliche Finanzverwaltung, in der Belege, Steuererklärung, Immobilien und weitere Themen zusammenlaufen.

## Language

**Datenebene** _(geprägt)_:
Der gemeinsame Unterbau: gespeicherte Daten und die Fachbausteine, die alle Module gleich brauchen (z. B. Dokument, Aussteller, Vertrag, Erwarteter Beleg, Schnappschuss, Geldbetrag, Zeitraum).
_Avoid_: Datalayer, Kern, Backend, Datenbank

**Modul**:
Ein Themenblock (z. B. Steuerjahr, Immobilie), der auf der Datenebene aufbaut und von anderen Modulen nur deren Ausgewiesene Werte sowie Adresse und Anzeigenamen ihrer Einträge kennt.
_Avoid_: Plugin, Tool, Feature

**Modulanmeldung** _(geprägt)_:
Was ein Modul beim Start der App über sich bekannt gibt, u. a.: seine Schlüssel im Wertekatalog samt Rechnung und Aufzählung der Bezugsobjekte, seine Eintragsarten, seine Dokumentarten und Auslese-Vorlagen, seine Befundarten und seine Seiten in der Oberfläche (Code: `ModuleRegistration`).
_Avoid_: Registry, Manifest, Plugin-Deklaration; „Anmeldung“ allein (klingt nach Login eines Nutzers oder nach Steueranmeldung)

**abschalten**:
Ein Nutzer erklärt für sich, dass ihn das Thema eines Moduls nicht betrifft: Das Modul verschwindet aus seiner Navigation, erzeugt keine Befunde, zählt keine Bezugsobjekte auf, und seine Ausgewiesenen Werte entfallen; die Daten bleiben erhalten, Wiedereinschalten stellt alles wieder her.
_Avoid_: deaktivieren, ausblenden (gilt für Befunde und den Eingang)

**Befund** _(geprägt)_:
Ein Punkt, der die Aufmerksamkeit eines Nutzers verdient (z. B. ausstehender Beleg, Abweichung zum Schnappschuss, auslaufender Vertrag), mit Schweregrad (Hinweis, Warnung, Fehler) und Verweis auf das Betroffene: einen Eintrag (z. B. Beleg, Vertrag, Bezugsobjekt), einen Ausgewiesenen Wert oder einen Einzelposten. Jeder Befund gehört zu einer **Befundart**, die die Datenebene oder ein Modul anmeldet.
Befunde werden auf Anfrage aus dem aktuellen Stand berechnet und verschwinden, sobald ihre Ursache behoben ist; ein Nutzer kann einen Befund mit Notiz ausblenden, bis sich der zugrunde liegende Stand ändert.
_Avoid_: Issue, Problem, Warnung oder Fehler (allein, das sind Schweregrade), quittieren, erledigen

**Befundliste** _(geprägt)_:
Die eine Stelle, an der alle nicht ausgeblendeten Befunde eines Nutzers zum gewählten Jahr über alle Module hinweg gesammelt werden; ausgeblendete Fehler zählt sie weiter mit.
_Avoid_: Review, Inbox, To-do, Durchsicht

**ausblenden**:
Etwas aus einer Liste nehmen, ohne es zu löschen. Einen Befund blendet ein Nutzer mit Pflicht-Notiz für sich aus, bis sich der zugrunde liegende Stand ändert; eine Datei im Eingang wird für alle Nutzer dauerhaft ausgeblendet. Gespeichert wird das als **Ausblendung**.
_Avoid_: quittieren, ignorieren, verwerfen

**Nutzer**:
Eine Person mit eigenen Daten, Belegen und Steuererklärungen; mehrere Nutzer sind möglich, ihre Daten bleiben getrennt.
_Avoid_: Account, Profil, Steuerpflichtiger

**Ausgewiesener Wert** _(geprägt)_:
Das Ergebnis einer Berechnung über Einzelposten, das ein Modul über die Datenebene für andere Module ausweist; er kann selbst in weitere Berechnungen eingehen. Genannt wird er über Schlüssel, Nutzer, ggf. Bezugsobjekt und Zeitbezug. Wie gerechnet wird, legt das Modul fest und hält es im Rechenweg fest. Sein Ergebnis ist genau eines von: ein Betrag mit Einzelposten und Rechenweg (Code: `ExposedValue`, nur für diesen Fall), **noch nicht berechenbar** oder **entfällt**; nie eine stille Null. Stützt sich ein Wert auf andere Werte, bilden sie eine **Kette**.
_Avoid_: Veröffentlichter Wert, Export, Schnittstelle, Wert (allein), Kennzahl (in ELSTER die Feldnummer), Kennwert

**noch nicht berechenbar**:
Ergebnis eines Ausgewiesenen Werts, dem ein Einzelposten fehlt, dessen Fehlen seine Rechnung nicht ausdrücklich regelt; mit Grund und, wenn es an einem anderen Wert hängt, der Kette. Ebenso ist jeder Wert noch nicht berechenbar, der auf ihm aufbaut. Ergibt einen Fehler-Befund (Code: `NotYetComputable`).
_Avoid_: unvollständig, nicht vorhanden

**entfällt**:
Ergebnis eines Ausgewiesenen Werts, der fachlich nicht zutrifft, mit Grund im Rechenweg (z. B. „Modul Dienstreisen abgeschaltet“); weder ein Betrag noch „noch nicht berechenbar“, und ohne Befund (Code: `NotApplicable`). Die Datenebene liefert es für die Werte abgeschalteter Module; eine Modul-Rechnung darf es nur als ausdrückliche Entscheidung liefern. Geht ein entfallender Wert in eine andere Rechnung ein, fehlt dort sein Einzelposten, und der Rechenweg nennt den Grund.
_Avoid_: leer, n/a, null, nicht vorhanden

**Einzelposten** _(geprägt)_:
Eine Zahl mit eigener Einheit, die in die Berechnung eines Ausgewiesenen Werts eingeht, mit Fundstelle und Belegstand; die Quelle ergibt sich aus der Fundstelle (Code: `LineItem`).
_Avoid_: Position, Zeile, Buchung

**Rechenweg**:
Die festgehaltene Folge der Schritte, mit der ein Modul einen Ausgewiesenen Wert berechnet hat: Einzelposten, Zwischenergebnisse und Entscheidungen; für alle Module gleich dargestellt und im Schnappschuss mit eingefroren (Code: `Workings`).
_Avoid_: Formel, Herleitung, Trace

**Fundstelle** _(geprägt)_:
Worauf sich ein Einzelposten stützt: eine Stelle in einem Dokument (Seite/Zeile), ein eDaten-Satz aus Mein ELSTER, ein Erwarteter Beleg, eine Nutzereingabe (genannt über ihre Adresse) oder ein anderer Ausgewiesener Wert (dann erbt der Einzelposten dessen Betrag und schwächsten Belegstand und hat keine eigene Quelle). Aus der Art der Fundstelle ergibt sich der Belegstand. Eine Stelle in einem Dokument nennt auch die Quelle, denn dasselbe Dokument kann ausgelesen und eingelesen sein (Code: `Locator`).
_Avoid_: Referenz, Quelle (die Fundstelle ist die genaue Stelle, die Quelle der Kanal)

**Quelle**:
Der Kanal, über den Daten von außen in MoarCoal gelangen: eDaten-Abruf aus Mein ELSTER, Dokumentauslesung (von Claude ausgelesen und bestätigt, z. B. Bank-PDF, Bescheid), Einlesung (exakt, ohne Claude, z. B. Übertragungsprotokoll) oder Nutzereingabe; alles, was von außen kommt, hat genau eine Quelle. Sie steht an der Fundstelle, nicht am Dokument (Code: `Source`).
_Avoid_: Herkunft, Import, Datenquelle

**Nutzereingabe**:
Ein von Hand erfasster Betrag mit Datum und Beschreibung, eingebettet in eine eigene Eintragsart des Moduls; als Fundstelle ergibt sie den Belegstand angenommen (Code: `UserInput`).
_Avoid_: manuelle Buchung, Handeingabe

**Arbeit**:
Das Modul für die Angaben zur nichtselbständigen Arbeit (Anlage N), im Durchstich von Hand erfasst: erste Tätigkeitsstätte und Arbeitsmittel. Modulschlüssel `work`.

**Erste Tätigkeitsstätte**:
Der Ort, an dem ein Nutzer dauerhaft arbeitet; erfasst werden je Steuerjahr die Arbeitstage und die einfache Entfernung in km von der Wohnung dorthin (Code: `FirstWorkplace`); sie ist das Bezugsobjekt der Ausgewiesenen Werte Arbeitstage und einfache Entfernung.

**Arbeitsmittel**:
Werkzeug und Material, das ein Nutzer für die Arbeit selbst gekauft hat; erfasst wird je Anschaffung ein Betrag als Nutzereingabe mit dem Steuerjahr, für das er gilt (Code: `WorkEquipment`).

**Belegstand** _(geprägt)_:
Ob ein Einzelposten durch einen Beleg gedeckt ist; er ergibt sich aus der Art der Fundstelle: belegt (Fundstelle ist eine Stelle in einem Dokument oder ein eDaten-Satz), ausstehend (Fundstelle ist ein Erwarteter Beleg, der Betrag gilt, bis der Beleg da ist) oder angenommen (Fundstelle ist eine Nutzereingabe, kein Beleg zu erwarten). Stützt sich ein Einzelposten auf einen anderen Ausgewiesenen Wert, erbt er dessen schwächsten Belegstand. Vom schwächsten zum stärksten: ausstehend, angenommen, belegt. Der Belegstand eines Ausgewiesenen Werts ist der schwächste seiner Einzelposten; ohne Einzelposten (z. B. ausdrücklich 0) ist er belegt (Code: `Backing`).
_Avoid_: Gewissheit, Status, geschätzt, geplant, vorläufig

**Bezugsobjekt** _(geprägt)_:
Der Eintrag, auf den sich ein Ausgewiesener Wert bezieht (z. B. eine Immobilie); er gehört dem Modul, das ihn führt, und andere Module kennen von ihm nur Adresse, Anzeigenamen und seine Ausgewiesenen Werte. Welche Bezugsobjekte es zu einem Schlüssel und Zeitbezug gibt, zählt das Modul auf, dem der Schlüssel gehört (Code: `Subject`).
_Avoid_: Entität; „Objekt“ nur im Immobilienmodul für die Immobilie selbst

**Zeitbezug**:
Wofür ein Ausgewiesener Wert gilt: ein Zeitraum (bei Zeitraumwerten) oder ein Stichtag (bei Stichtagswerten); welches von beiden, legt der Wertekatalog je Schlüssel fest (Code: `TimeRef`).
_Avoid_: Periode

**Zeitraum**:
Ein zusammenhängendes Intervall von Tagen, meist ein Kalenderjahr, z. B. der Zeitbezug eines Zeitraumwerts oder der Bezugszeitraum eines Dokuments (Code: `Period`).
_Avoid_: Periode, Veranlagungszeitraum (steuerrechtlich enger)

**Stichtagswert** _(geprägt)_:
Ein Ausgewiesener Wert, der für einen Tag, den Stichtag, gilt (z. B. Restschuld am 31.12.; Code für den Stichtag: `KeyDate`); Stichtagswerte werden nicht über Zeiträume summiert (ihre Einzelposten schon).
_Avoid_: Bestand, Saldo

**Zeitraumwert** _(geprägt)_:
Ein Ausgewiesener Wert, der für einen Zeitraum gilt (meist ein Kalenderjahr, z. B. Mieteinnahmen 2025). Zeitraumwerte aufeinanderfolgender Zeiträume bilden eine Zeitreihe; ob man sie addieren darf, entscheidet die Rechnung, die sie verwendet (Verhältniswerte nicht).
_Avoid_: Bewegung, Umsatz

**Schlüssel**:
Der stabile, fachlich benannte Name eines Ausgewiesenen Werts im Wertekatalog (z. B. `property.loan_interest`); er gehört genau einem Modul (Code: `ValueKey`).
_Avoid_: Kennung (das ist der zufällige Teil einer Adresse), Kennzahl

**Wertekatalog** _(geprägt)_:
Die Liste aller Schlüssel, die Module anmelden, mit Bedeutung, Einheit und Zeitbezug (Zeitraum oder Stichtag) (Code: `ValueCatalog`).
_Avoid_: Registry, Verzeichnis, Katalog (allein)

**Schnappschuss**:
Die zu einem Anlass (z. B. Abgabe einer Steuererklärung) eingefrorenen Ausgewiesenen Werte samt Einzelposten, auch solche, die noch nicht berechenbar waren oder entfallen (mit Grund). Ein Schnappschuss ist unveränderlich und hängt nicht vom Ablageort ab, denn die Dokumente, auf die er verweist, werden beim Einfrieren ins Datenverzeichnis kopiert; spätere Abweichungen von den aktuellen Werten werden sichtbar statt verhindert (Code: `Snapshot`; das Anlegen heißt einfrieren).
_Avoid_: Sperre, Abgabestand, Festschreibung, Version

**Aussteller**:
Wer ein Dokument ausgestellt hat (Bank, Versicherung, Finanzamt, Handwerker); geführt in einem eigenen Katalog mit Informationen je Aussteller, auf den Dokumente, Verträge (als Vertragspartner) und Erwartete Belege verweisen. Ein Aussteller ist ein Unternehmen oder eine Behörde, außer er ist als **Privatperson** gekennzeichnet (z. B. privater Vermieter); nur dann sind Name und Anschrift sensibel.
_Avoid_: Absender, Firma (im HGB der Handelsname), Gegenpartei

**Eintrag**:
Etwas Gespeichertes in MoarCoal mit eigener Adresse, z. B. Dokument, Aussteller, Vertrag, Immobilie, Darlehen, Dienstreise. Ausgewiesene Werte und ihre Einzelposten sind berechnet und keine Einträge; Ausblendungen, Vorschläge und die Ausnahmen eines Erwarteten Belegs sind gespeichert, hängen aber an einem Eintrag und haben keine eigene Adresse.
_Avoid_: Datensatz, Objekt, Entität, Record

**Eintragsart**:
Was für ein Eintrag es ist (z. B. Immobilie, Darlehen, Dokument); fachlich benannt, über alle Module eindeutig und genau einem Modul oder der Datenebene zugehörig, festgehalten in der Modulanmeldung. Im Code ist sie der Klassenname des Eintrags.
_Avoid_: Typ, Klasse, Kategorie

**Adresse**:
Wie ein Eintrag überall in MoarCoal genannt wird (in Notizen, Befunden, Fundstellen, Zuordnungen und Links): seine Eintragsart plus eine **Kennung**, die beim Anlegen zufällig vergeben wird, keine Bedeutung trägt und sich nie ändert (Code: `EntryAddress`).
_Avoid_: Referenz, Link, Pfad, URL (das ist der Link zur Seite des Eintrags); für die Postanschrift heißt es Anschrift

**zuordnen**:
Ein Dokument oder einen Erwarteten Beleg einem anderen Eintrag zuweisen, den es betrifft (z. B. einem Vertrag oder einer Immobilie); die Zuordnung steht am Dokument bzw. Erwarteten Beleg, egal welchem Modul der andere Eintrag gehört.
_Avoid_: verknüpfen, verlinken, taggen

**Notiz**:
Ein freier Text eines Nutzers mit Datum, der an einen beliebigen Eintrag in MoarCoal gehängt werden kann (z. B. Beleg, Vertrag, Bezugsobjekt), etwa um eine Abweichung zu erklären; ebenso die Pflicht-Notiz einer Ausblendung und die Notiz zu einer Ausnahme eines Erwarteten Belegs. Nicht an Berechnetes, denn Einzelposten und Ausgewiesene Werte entstehen bei jeder Anfrage neu.
_Avoid_: Kommentar, Anmerkung, Memo

**Vorgang**:
Eine Schreibänderung über die Datenebene, die beliebig viele Einträge in mehreren Dateien ganz oder gar nicht ändert; der einzige Weg, auf dem Module und Datenebene schreiben. Er besteht aus **Änderungen**; ihre Folgen (z. B. beim Löschen) rechnet die Datenebene selbst aus. Kein eigener Typ im Code, sondern ein Aufruf von `apply`.
_Avoid_: Transaktion, Commit

**Änderung**:
Ein Teil eines Vorgangs: einen Eintrag anlegen oder ersetzen, löschen oder zwei Einträge zusammenführen; trägt die Prüfsumme des Eintrags, die der Aufrufer kannte (Code: `Change`).
_Avoid_: Patch, Mutation, Diff

**Stand**:
Alle geladenen Einträge im Arbeitsspeicher, unveränderlich; jede Anfrage hält zu Beginn den aktuellen Stand fest und liest nur aus ihm, ein Vorgang ersetzt ihn als Ganzes. Ein Modul sieht ihn nur eingegrenzt auf sich und einen Nutzer (Code: `State`, eingegrenzt `ModuleState`).
_Avoid_: Cache, Snapshot (das ist der Schnappschuss), Kontext

**Dokument**:
Eine aufgenommene Datei, auf die MoarCoal an einem Ablageort verweist oder die es ins Datenverzeichnis übernommen hat (z. B. Rechnung, Kontoauszug, Bescheid, Mietvertrag), mit Aussteller, Datum und höchstens einer Dokumentart; vor dem Aufnehmen heißt sie Datei.
_Avoid_: Unterlage, Anhang

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
Eine Datei aus dem Eingang zum Dokument machen; danach wird sie je nach Dokumentart eingelesen, ausgelesen oder beides. Gegenstück: **ausblenden** (die Datei erscheint nicht mehr im Eingang).
_Avoid_: importieren, einlesen (für diesen Schritt)

**einlesen**:
Felder eines Dokuments mit festem Aufbau exakt und ohne Claude übernehmen (z. B. Übertragungsprotokoll); das Ergebnis gilt ohne Bestätigung, wird nie von Hand korrigiert und beim Start neu eingelesen, wenn sich das Einlesen geändert hat.
_Avoid_: importieren, parsen

**auslesen**:
Felder eines Dokuments nach der Auslese-Vorlage seiner Dokumentart von Claude lesen lassen; das Ergebnis ist ein Vorschlag, der erst nach Bestätigung gilt. Gegenstück: einlesen (exakt, ohne Claude, ohne Bestätigung).
_Avoid_: importieren, extrahieren, parsen

**Vorschlag**:
Das Ergebnis einer Auslesung an einem Dokument: Felder mit Inhalt und Stelle im Dokument (Seite/Zeile), die erst nach Bestätigung durch den Nutzer (je Feld, ggf. korrigiert) in Daten eines Moduls übergehen; bleibt danach samt Korrekturen erhalten (Code: `Proposal`).
_Avoid_: Entwurf, Vorschlagswert, unbestätigter Einzelposten

**Auslese-Vorlage** _(geprägt)_:
Was ein Modul für eine Dokumentart auslesen lassen will: Liste der Felder mit Einheit und Hinweis für Claude (Code: `ExtractionTemplate`).
_Avoid_: Prompt, Schema, Formular, Vorlage (allein, das sind die Jinja-Vorlagen der Oberfläche)

**Beleg**:
Ein Dokument, sofern es einen Betrag nachweist, auf den sich ein Einzelposten stützt oder (als Erwarteter Beleg) stützen soll; Beleg ist eine Rolle, kein Merkmal am Dokument, und nicht jedes Dokument ist einer.
_Avoid_: Quittung, Nachweis

**Erwarteter Beleg**:
Ein Beleg, der regelmäßig oder einmalig kommen soll, z. B. jährlich die Zinsbescheinigung zu einem Darlehen: Aussteller, Dokumentart, die Einträge, die er betrifft, Rhythmus mit Beginn und Ende sowie Beschaffungsweg und Beschaffungshinweis. Ein Eintrag, der von Beginn bis Ende gilt; für jeden Zeitraum seines Rhythmus ergibt sich daraus, welches Dokument fällig ist, ohne dass jährlich etwas neu angelegt wird. Er ist **erfüllt**, sobald ein passendes Dokument da ist; fällt er für einen Zeitraum aus, trägt er dafür eine Ausnahme mit Notiz.
_Avoid_: Checkliste, Erwartung (allein), offener Beleg, Platzhalter

**Dokumentart**:
Was für ein Dokument es ist (z. B. Zinsbescheinigung, Grundsteuerbescheid, Darlehensvertrag); Module melden ihre Dokumentarten an, die Datenebene einige allgemeine. Jedes Dokument hat höchstens eine. Die Dokumentart legt fest, ob ihre Dokumente einen **Bezugszeitraum** haben, den Zeitraum, für den das Dokument gilt (z. B. Zinsbescheinigung 2025, ausgestellt 2026); andere gelten ohne zeitliche Grenze (z. B. Darlehensvertrag).
_Avoid_: Belegtyp, Dokumenttyp, Kategorie

**Beschaffungsweg**:
Wie ein Erwarteter Beleg zu beschaffen ist, aus einer festen Liste (Post, Online-Postfach des Ausstellers, E-Mail, eDaten aus Mein ELSTER, selbst erstellen); dazu der **Beschaffungshinweis** als freier, sensibler Text, nie mit Zugangsdaten.
_Avoid_: Bezugsweg („Bezug“ heißt sonst Referenz, im Steuerrecht sind Bezüge Einkünfte), Kanal, Quelle (die Quelle ist der Weg in MoarCoal, nicht zum Nutzer)

**Vertrag**:
Eine Vereinbarung eines Nutzers mit einem Aussteller als Vertragspartner (z. B. Versicherung, Darlehen, Mietvertrag, Strom) mit Vertragsnummer und Laufzeit, dem Dokumente zugeordnet werden; nach ihrem Ende bleibt sie ein Vertrag. Was der Vertrag fachlich bedeutet, weiß das Modul.
_Avoid_: Police, Konto, Abo; für die Vereinbarung zwischen Schnittstellen heißt es Contract

**sensibel**:
Eigenschaft eines Felds (nicht eines einzelnen Inhalts): sein Inhalt sind echte persönliche Daten (z. B. Name, Anschrift, Vertragsnummer) und darf nicht in git, auf GitHub oder ins Protokoll der App gelangen; an Claude darf er auf Anforderung des Nutzers gehen.
_Avoid_: geheim, vertraulich, privat

**Sperrliste**:
Die Werte, die die Datenschutz-Prüfung vor git und GitHub abfängt: von Hand gepflegt oder aus den sensiblen Feldern der gespeicherten Daten abgeleitet.
_Avoid_: Denylist, Blacklist, Filterliste
