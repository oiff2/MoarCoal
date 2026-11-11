# Belege verweisen statt kopieren; eigenes Datenverzeichnis

MoarCoal hält seine Daten in einem eigenen Datenverzeichnis `~/MoarCoal/` (lokal im WSL-Dateisystem, nicht in einem Sync-Ordner), gegliedert nach `users/<id>/<modul>/` und `common/`. Dokumente in der bestehenden Belegablage werden nicht kopiert, sondern über benannte Ablageorte verwiesen (Ablageort + relativer Pfad + SHA-256); nur Dateien ohne festen Ort (Uploads, Screenshots) werden inhaltsadressiert nach `users/<id>/documents/` übernommen.

Verworfen: App-Daten versteckt neben den Belegen (`<jahr>/.kohlebau/` wie im Vorgänger), weil jahresunabhängige Daten (Immobilie, Aussteller) und mehrere Nutzer schlecht in die Jahresordner passen und ein einziges Wurzelverzeichnis leichter zu sichern und zu versionieren ist. Verworfen: alles kopieren, weil die bestehende Ablage die Wahrheit bleibt und Dubletten entstünden.

Folgen: Verschwindet eine Datei, wird sie über ihren SHA-256 im Ablageort wiedergefunden; sonst entsteht ein Befund. Sync-Konflikte betreffen nur die Ablage, die MoarCoal nur liest.

## Nachtrag: Kopie beim Einfrieren

Ausnahme vom Verweisen: Beim Einfrieren eines Schnappschusses werden alle Dokumente, auf die eine Fundstelle in einem seiner Einzelposten verweist (über die ganze eingefrorene Kette, also auch in den Werten, auf die er sich stützt), und das auslösende Dokument (z. B. Übertragungsprotokoll) inhaltsadressiert nach `users/<id>/documents/<sha256-prefix>/` kopiert (dedupliziert, gleicher Ort wie Uploads). Ein Schnappschuss darf nicht von Dateien am Ablageort abhängen, denn der abgegebene Stand muss auch Jahre später vollständig nachweisbar sein. Kopien werden nie gelöscht, solange ein Schnappschuss auf sie verweist.
