# Angaben zur Person als Baustein; der eigene Aussteller wird daraus abgeleitet

Der Name des Nutzers steht in den **Angaben zur Person** (Code: `PersonalDetails`), einem Baustein der Datenebene wie Dokument und Aussteller, nicht in einem Modul. Er gehört dem Nutzer, es gibt genau einen je Nutzer (die Prüfung läuft im Schreibweg, [ADR 0006](0006-schreibweg-vorgang-mit-journal.md)), und er trägt Vorname, Name und die Adresse des eigenen Ausstellers. Ein Nutzer entsteht mit seinen Angaben zur Person; ohne sie zeigt MoarCoal nur die Startseite mit dem Formular, jede andere Seite leitet dorthin um. Vorerst gibt es den festen Nutzer `"ich"`; Nutzerliste und Nutzerwechsel kommen mit dem Prototyp der Oberfläche (#62). Es gibt keine Migration: Vorhandene Daten erscheinen, sobald der Name eingetragen ist.

Der Name soll in der Sperrliste stehen, aber nur an einer Stelle. Deshalb legt die App beim Speichern der Angaben den **Aussteller** „Vorname Name“ als Privatperson an und hält ihn gleich, in demselben Vorgang. Die Angaben verweisen auf ihn; die Adresse wird über `merged_ids` aufgelöst, ist sie leer oder nicht auflösbar, entsteht der Aussteller neu. Gibt es im Katalog schon genau einen Aussteller mit diesem Namen oder Alias, wird er übernommen und als Privatperson gekennzeichnet. Ändert sich der Name, wird der alte Name Alias, bleibt also in der Suche und in der Sperrliste. Der Name gelangt nur über `Issuer.sensitive_values` in die abgeleitete Sperrliste (ganzer Name, Teile ab 6 Zeichen), die Angaben selbst tragen kein `Sensitive`. Auf der Seite des Ausstellers sind Name und Privatperson nur lesbar (mit Hinweis und Link auf die Angaben), Löschen ist gesperrt, denn die Angaben verweisen auf ihn; Aliasse und Zusammenführen bleiben wie bisher.

Der Aussteller ist gemeinsam (`COMMON_OWNER`, wie jeder Aussteller). Bei mehreren Nutzern sieht ihn jeder. Das ist gewollt: Er kommt auf Belegen als Aussteller oder Empfänger vor, und ein Mensch hat genau einen Namen, egal wer gerade eingeloggt ist; ein Aussteller je Nutzer würde dieselbe Person doppelt führen.

Verworfen:
- **Ein eigenes Modul „Profil“**: Der Name wird von der Datenebene gebraucht (Aussteller, Sperrliste, Kopfzeile), die Datenebene darf kein Modul kennen (Prinzip 1). Der Umzug hinter das Nutzer-Symbol (#62) ändert so nur den Link in der Kopfzeile.
- **Name als `Sensitive`-Feld der Angaben**: Dann stünde er an zwei Stellen in der Sperrliste, und Alias-Pflege und Sperrliste liefen auseinander.
- **Platzhaltername für die Startseite**: Ohne Nutzer gibt es keinen Namen; ein erfundener Name wäre ein Wert, der wie echt aussieht.
- **Nutzer ohne Namen anlegen**: Die Sperrliste und der Aussteller brauchen den Namen, und eine Nutzerliste ohne Namen ist nichts, was man auswählen kann.

Siehe [Angaben zur Person](https://github.com/oiff2/MoarCoal/issues/124).
