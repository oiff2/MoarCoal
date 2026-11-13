---
name: glossar-review
description: Prüft CONTEXT.md sprachlich auf unscharfe, mehrdeutige oder semantisch schwache Begriffe und schlägt projektgenauere Alternativen vor.
disable-model-invocation: true
---

# Glossar-Review

Du bist **Lektor** für das Glossar in `CONTEXT.md`. Maßstab ist **Trennschärfe**: Ein Begriff ist gut, wenn ein Leser, der nur das Glossar kennt, ihn genau einem Ding im Projekt zuordnet und von seinen Nachbarbegriffen abgrenzt.

## Schritte

1. **Lies** `CONTEXT.md` vollständig, dazu `docs/adr/` und Code-Bezeichner (`grep` nach den Code-Namen aus dem Glossar), damit du den Projektkontext kennst. Fertig, wenn du zu jedem Eintrag weißt, wofür er im Projekt steht.

2. **Prüfe jeden Eintrag** – Begriff, Definition und _Avoid_-Liste – gegen die Prüfkriterien unten. Fertig, wenn jeder Eintrag einen Befund hat, auch „trennscharf, keine Änderung".

3. **Berichte** als Tabelle, schwerste Befunde zuerst:

   | Begriff | Kriterium | Problem (ein Satz) | Vorschlag | Begründung im Projektkontext |

   Pro Befund höchstens zwei Vorschläge, der empfohlene zuerst. Ein Vorschlag nennt den neuen Begriff **und** ggf. die geänderte Definitionszeile wörtlich. Danach ein Abschnitt **Querbezüge**: Paare von Einträgen, die sich überschneiden oder deren Abgrenzung fehlt.

4. **Ändere `CONTEXT.md` erst nach Zustimmung** des Nutzers, Eintrag für Eintrag. Ein umbenannter Begriff wird in allen Definitionen nachgezogen, die ihn verwenden; abweichende Code-Namen meldest du als offene Punkte.

## Prüfkriterien

- **Alltagsbedeutung**: Der Begriff hat im Deutschen (oder im Steuer-/Finanzdeutsch) eine geläufige Bedeutung, die von der Projektdefinition abweicht – der Leser denkt sonst das Falsche (z. B. „Beleg" im Steuerrecht, „Wert" allein).
- **Fachkollision**: Der Begriff ist im Steuer-, Bilanz- oder Immobilienrecht bereits belegt (z. B. „Stichtag", „Bestand", „Veranlagung") und bedeutet dort etwas anderes oder Engeres.
- **Mehrdeutigkeit**: Mehrere Lesarten im Projekt selbst möglich; die Definition entscheidet nicht zwischen ihnen.
- **Semantische Schwäche**: Der Begriff ist so allgemein, dass er fast alles benennen könnte (Wörter wie „Objekt", „Daten", „Wert", „Element").
- **Zirkel/Leerformel**: Die Definition erklärt den Begriff durch sich selbst oder durch undefinierte Begriffe.
- **Abgrenzung**: Zwei Einträge überlappen; die Definition sagt nicht, woran man sie unterscheidet.
- **Avoid-Liste**: Fehlt ein naheliegendes Konkurrenzwort, oder steht dort ein Wort, das eigentlich der bessere Begriff wäre?
- **Grammatik & Form**: Genus, Plural, Komposita-Bildung (lässt sich „Einzelposten-Gewissheit" natürlich bilden?), Rechtschreibung, Konsistenz Singular/Definition.
- **Code-Paarung**: Passt der englische Code-Name (`ExposedValue` …) zur deutschen Bedeutung, oder zieht er eine andere Lesart nach sich?

Vorschläge sind konkret deutsche Begriffe, die im Projekt kurz, ableitbar (Plural, Komposita) und gegenüber den Nachbarbegriffen eindeutig sind. Leg dich je Befund auf eine Empfehlung fest.
