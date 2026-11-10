# Absicherung: Host- und Origin-Prüfung statt Token, Claude ohne Werkzeuge

Abgesichert wird gegen zwei Angreifer: eine beliebige Webseite im Windows-Browser, die Anfragen an den lokalen Server schickt (CSRF, per DNS-Rebinding auch lesend), und eingeschleuste Anweisungen in einem Dokument, das Claude ausliest. Andere Prozesse desselben Nutzers gehören nicht dazu, denn sie können `~/MoarCoal/` ohnehin direkt lesen. Geräte im LAN erreichen den Server nicht, weil er nur an `127.0.0.1` lauscht (ADR 0002).

**Server.** Eine Middleware für alle Seiten weist jede Anfrage ab, deren `Host` nicht `127.0.0.1:<port>` oder `localhost:<port>` ist; das schließt DNS-Rebinding aus. Ändernde Anfragen (alles außer GET/HEAD) brauchen einen `Origin` gleich dem eigenen Origin (`http://127.0.0.1:<port>` bzw. `http://localhost:<port>`) oder `Sec-Fetch-Site: same-origin`. GET ändert nie etwas, es gibt kein CORS. Jede Antwort trägt eine strikte CSP (`default-src 'self'`, kein Inline-Skript, `connect-src 'self'`, `frame-ancestors 'none'`) und `X-Content-Type-Options: nosniff`. Jinja escaped überall, auch Claude-Ausgaben und Dateinamen aus Dokumenten. htmx wird nur über Attribute oder eine eigene JS-Datei konfiguriert.

**Claude.** Ein einziger Aufrufbaustein hinter der Auslese-Schnittstelle ruft `claude -p` mit fester Argumentliste auf: `--tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --input-format stream-json --output-format stream-json`, als Arbeitsverzeichnis ein leeres Wegwerfverzeichnis. Er prüft die `init`-Meldung: Ist `tools` oder `mcp_servers` nicht leer, bricht er ab und meldet einen Fehler-Befund. So fällt es auf, wenn ein CLI-Update das Verhalten ändert. Ein Test prüft die Argumentliste. Das Dokument geht als base64-`document`-Block (PDF) bzw. `image`-Block an Claude; andere Formate werden vorher lokal umgewandelt. Die Antwort muss gegen das aus der Auslese-Vorlage erzeugte JSON-Schema passen und wird danach mit Pydantic geprüft. Felder außerhalb der Vorlage werden verworfen. Das Ergebnis ist immer nur ein Vorschlag, der je Feld bestätigt wird. Gegen falsche Werte aus einer Einschleusung schützt diese Bestätigung, nicht der Aufruf.

Verworfen:
- **Token für ändernde Anfragen**: Ohne Cookies und Login gibt es nichts, was eine fremde Seite mitnutzen könnte. Host- und Origin-Prüfung decken CSRF und Rebinding schon ab.
- **`--bare`**: Es liest kein OAuth, damit ginge das Pro-Abo nicht.
- **Read-Werkzeug auf eine Datei beschränkt**: Claude bräuchte dafür Werkzeuge, die Grenze hinge an der Werkzeugkonfiguration.
- **Text lokal extrahieren**: Layout und Scans gingen verloren. Nur für Dokumentarten, die reiner Text sind.

Siehe [Absicherung des lokalen Servers und des Claude-Aufrufs](https://github.com/oiff2/MoarCoal/issues/23).
