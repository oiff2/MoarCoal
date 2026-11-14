# Karte der Dienstreisen: feste Grundkarte, Ortssuche nur auf Klick

Die Seite Dienstreisen zeigt eine Karte von Deutschland mit den Startorten und Reisezielen eines Jahrs (#114). Die Orte sind Freitext („Musterstadt“), eine Lage muss also von irgendwoher kommen. Der Startort verrät den Wohnort, deshalb geht nichts über die Reisen ungefragt nach außen (ADR 0002, ADR 0007, Prinzip 8).

**Grundkarte.** `modules/work/germany_map.json` hält Umriss und Landesgrenzen als SVG-Pfade; `scripts/make_germany_map.py` erzeugt die Datei einmal aus Natural Earth 1:10m Admin 1 (gemeinfrei) und vereinfacht sie auf rund 36 kB. Die App holt nie Kacheln oder Geodaten, es gibt kein CDN; die Farben kommen aus CSS, ohne Inline-Style (CSP).

**Lage per Suche auf Klick.** Ein Ort ohne Lage steht unter der Karte mit einem Suchfeld, das den Ortsnamen schon enthält, und der Schaltfläche „Suchen“. Nur auf diese POST-Anfrage fragt der Server Nominatim (OpenStreetMap), beschränkt auf Deutschland, höchstens eine Anfrage je Sekunde, mit einem allgemeinen User-Agent ohne Kontaktdaten. Gesendet wird nur der getippte Text, nichts zu Reise, Datum oder Jahr. Der Nutzer wählt einen Treffer (Name und Bundesland sind sichtbar); bei Fehler oder ohne Treffer erscheint eine Meldung und nichts wird gespeichert. GET ändert und fragt nie etwas.

**Die Suche ist ein Aufrufbaustein** (`moarcoal.place_search`), wie der Claude-Aufruf: `create_app(place_search=...)` legt ihn auf `app.state`, Tests geben einen Fake mit und berühren nie das Netz.

**Gespeichert** wird als Eintrag `Place` über `apply`, einmal für alle Jahre (Datei `users/<Nutzer>/work/places.json`), je Nutzer und Ortsname höchstens einer. „Nicht zeigen“ (z. B. Ausland) ist derselbe Eintrag mit `hidden`; „vergessen“ löscht ihn.

Verworfen: Offline-Ortsverzeichnis (groß, und eine falsche Vermutung ist schlimmer als Nachfragen), Setzen per Klick auf die Karte, Zoom und Verschieben.
