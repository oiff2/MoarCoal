# Optik-Prototyp (#231), wegwerfen

Wegwerf-Prototyp für #207: Belege-Seite und eine Anlage-Seite des Steuerjahrs in drei Varianten, hell und dunkel, dazu drei Entwürfe für das App-Icon. Nur erfundene Beispielwerte. Nichts hiervon gehört nach `src/`; übernommen wird erst nach der Wahl (#232 ff.).

Start (ein Befehl, im Repo-Wurzelordner):

    uv run python prototypes/optik/serve.py

Dann <http://127.0.0.1:8231/> öffnen, Strg+C beendet. Der Server liest nur diesen Ordner, speichert nichts und lädt nichts von außen (`default-src 'self'`, keine Inline-Stile).

- Seiten: `/belege`, `/steuerjahr` (Anlage N), `/app-icon` (alle Entwürfe, Vergleich mit Kohlebau).
- Schalter unten in der Leiste: Variante A/B/C, Darstellung System/Hell/Dunkel, App-Icon 1/2/3. Oder in der Adresse: `?v=b&d=dunkel&i=2`.
- Varianten: A Tabelle (Kohlebau-nah, Feldkarten), B Liste mit Detailspalte (ruhig, luftig, Feldtabelle), C dicht und warm (Bernstein-Akzent, Streifen je Feld).

Aufbau, zugleich der Vorschlag für die Übernahme: `static/tokens.css` (nur Tokens, die Varianten überschreiben sie), `static/bausteine.css` (Grundelemente und Bausteine), `static/seiten.css` (nur Raster), `templates/_ui.html` (ein Makro je Baustein, Icons nur über `icon()`), `static/proto.js` (ein Modul, gesteuert über `data-`-Attribute), `static/icons/` (Lucide, ISC, aus Kohlebau kopiert; Sonne und Mond ergänzt).
