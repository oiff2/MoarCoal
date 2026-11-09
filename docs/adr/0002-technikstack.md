# Technikstack: Python, lokaler Webserver, kein Build-Schritt

MoarCoal ist eine Python-Anwendung (uv, strikte Typprüfung), die als lokaler Webserver nur an `127.0.0.1` auf einem festen, konfigurierbaren Port läuft; ist der Port belegt, bricht der Start ab, statt auszuweichen, damit Lesezeichen gültig bleiben. Jede Seite hat eine eigene URL, die sich direkt im Windows-Browser öffnen lässt. Gestartet wird per Windows-Verknüpfung mit kleinem Ladebalken, danach öffnet sich der Browser; der Server beendet sich selbst, wenn keine Seite mehr offen ist.

Die Oberfläche ist serverseitig gerendert (FastAPI + Jinja2 + htmx), ohne Build-Schritt und ohne npm; Fremd-JS liegt als Datei im Repo, nicht auf einem CDN, weil nichts automatisch nach außen gehen soll. Pydantic prüft auch die Daten der Datenebene. Claude wird über `claude -p` mit dem Pro-Abo angesprochen (kein API-Key), hinter der Schnittstelle der Datenebene fürs Auslesen; Tests laufen mit einem Fake.

Verworfen: Desktop-Hülle (Tauri/Electron) und JS-Framework mit Build, weil sie npm und eine Build-Kette bringen, ohne für eine lokale Einzelnutzer-App etwas zu gewinnen, das Tabs, Links und die Zurück-Taste des Browsers nicht schon liefern; Django, weil ORM und Admin bei JSON-Speicher ungenutzt blieben. Siehe [Technikentscheidung festhalten](https://github.com/oiff2/MoarCoal/issues/8).
