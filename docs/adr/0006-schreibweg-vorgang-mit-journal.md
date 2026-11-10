# Schreibweg: ein Prozess, Stand im Arbeitsspeicher, Vorgang mit Journal

MoarCoal läuft als ein einziger Server-Prozess. Beim Start lädt die Datenebene alle Daten in den Arbeitsspeicher als unveränderlichen Stand. Jede Anfrage hält sich zu Beginn den aktuellen Stand fest und liest ohne Sperre daraus. Geschrieben wird nur über eine Stelle der Datenebene, hinter einer einzigen Schreibsperre im Prozess. Auch Migration und Neu-Einlesen beim Start laufen darüber.

Ein Modul schreibt in einem **Vorgang**, der beliebig viele Einträge über mehrere Dateien ändern kann. Beim Abschluss prüft die Datenebene alles mit Pydantic. Sie vergleicht die Prüfsumme jeder betroffenen Datei mit der beim Laden gemerkten, denn Handänderungen während des Betriebs werden abgewiesen statt überschrieben. Außerdem vergleicht sie die Prüfsumme jedes Eintrags mit der, die das Formular mitbringt, denn ein veralteter Tab wird mit „inzwischen geändert“ abgewiesen. Danach sichert sie die alte Fassung nach `.backup/` (die letzten 20 je Datei), schreibt alle neuen Dateien als temporäre Dateien mit `fsync` und legt dann ein Journal der geplanten Umbenennungen an. Anschließend benennt sie um und löscht das Journal. Erst dann wird der neue Stand mit einer einzigen Zuweisung eingetauscht. Scheitert etwas vor dem Journal, ist nichts geändert. Findet der Start ein Journal vor, führt er es zu Ende, noch vor Archiv und Migration. Die abgeleitete Sperrliste wird nach dem Abschluss neu geschrieben, wenn ein sensibles Feld betroffen war, und beim Start immer. Scheitert das, entsteht ein Befund, kein Abbruch.

Verworfen:
- **Reihenfolge je Ablauf statt Journal**: Jeder Ablauf müsste einzeln so sortiert werden, dass jeder Zwischenstand gültig ist. Beim Bestätigen eines Vorschlags droht sonst doppelte Übernahme.
- **Sperrdateien bzw. `fcntl`**: Ein zweiter Prozess ist durch den festen Port schon ausgeschlossen.
- **Lesen von der Platte je Anfrage**: Das ist langsamer und gäbe keinen festen Stand je Anfrage.
- **Lesen unter der Sperre**: Lange Rechnungen würden das Speichern blockieren.

Siehe [Schreibweg der Datenebene](https://github.com/oiff2/MoarCoal/issues/22).
