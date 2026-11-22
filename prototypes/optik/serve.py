"""PROTOTYP, wegwerfen (#231): Optik-Varianten für Belege und Steuerjahr, erfundene Werte.

Start: uv run python prototypes/optik/serve.py   ->   http://127.0.0.1:8231/
Nichts wird gespeichert, nichts geladen, was nicht in diesem Ordner liegt.
"""

import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

HERE = Path(__file__).parent
STATIC = HERE / "static"
ICONS = STATIC / "icons"
PORT = 8231
VARIANTS = {"a": "Tabelle", "b": "Liste mit Detailspalte", "c": "Dicht und warm"}
APP_ICONS = {"1": "Haufen", "2": "Plus", "3": "M"}

_SVG_INNER = re.compile(r"<svg[^>]*>(.*)</svg>", re.S)


def icon_inner(name: str) -> Markup:
    """Der Inhalt einer Lucide-Datei ohne den <svg>-Rahmen; nur das Icon-Makro ruft das auf."""
    text = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    return Markup(_SVG_INNER.search(text).group(1).strip())  # noqa: S704


env = Environment(
    loader=FileSystemLoader(HERE / "templates"),
    autoescape=select_autoescape(["html"]),
    auto_reload=True,
)
env.globals["icon_inner"] = icon_inner

# Erfundene Beispielwerte (keine echten Daten).
NEU = [
    {
        "name": "Rechnung_Werkzeughandel_0412.pdf",
        "pfad": "Jahresordner 2025/Werkstatt",
        "typ": "pdf",
        "groesse": "84 KB",
    },
    {"name": "Scan_0007.jpg", "pfad": "Jahresordner 2025", "typ": "bild", "groesse": "1,2 MB"},
    {
        "name": "eDaten_Lohnsteuer_Beispiel.html",
        "pfad": "Jahresordner 2025/eDaten",
        "typ": "html",
        "groesse": "31 KB",
    },
    {"name": "Kontoauszug_2025_07.pdf", "pfad": "Scan-Eingang", "typ": "pdf", "groesse": "212 KB"},
]
ERWARTET = [
    {"name": "Beispielbank · Jahressteuerbescheinigung", "zeitraum": "2025", "stand": "ausstehend"},
    {"name": "Musterversicherung · Beitragsbescheinigung", "zeitraum": "2025", "stand": "da"},
]
AUFGENOMMEN = [
    {
        "name": "Musterfirma · Lohnsteuerbescheinigung",
        "pfad": "Jahresordner 2025/Lohn",
        "typ": "pdf",
        "art": "Lohnsteuerbescheinigung",
        "eintraege": 3,
        "stand": "fertig",
        "stand_art": "gut",
    },
    {
        "name": "Beispielbank · Kontoauszug 03/2025",
        "pfad": "Jahresordner 2025/Bank",
        "typ": "pdf",
        "art": "Kontoauszug",
        "eintraege": 1,
        "stand": "zu bestätigen",
        "stand_art": "warnung",
    },
    {
        "name": "Werkzeughandel · Rechnung Akkuschrauber",
        "pfad": "Jahresordner 2025/Werkstatt",
        "typ": "pdf",
        "art": "Beleg",
        "eintraege": 1,
        "stand": "Beleg",
        "stand_art": "still",
    },
    {
        "name": "Musterstadt · Grundsteuerbescheid",
        "pfad": "Jahresordner 2025",
        "typ": "bild",
        "art": "Grundsteuerbescheid",
        "eintraege": 0,
        "stand": "auszulesen",
        "stand_art": "hinweis",
        "befund": "Auf diesen Beleg verweist kein Eintrag",
    },
    {
        "name": "Beispielbank · Zinsbescheinigung 2024",
        "pfad": "Ablage/Bank",
        "typ": "pdf",
        "art": "Zinsbescheinigung",
        "eintraege": 2,
        "stand": "fertig",
        "stand_art": "gut",
    },
]
# (Zeile, E-Kennung, Bezeichnung, Einheit, Art, Betrag/Text, Belegstand, Gegenproben, Grund)
ABSCHNITTE = [
    (
        "Bruttoarbeitslohn",
        [
            {
                "z": "4",
                "e": "E0100001",
                "bez": "Bruttoarbeitslohn",
                "einheit": "EUR",
                "art": "betrag",
                "wert": "48.000",
                "belegstand": "belegt",
                "proben": [
                    {"seite": "Lohnsteuerbescheinigung", "wert": "48.000 EUR", "ok": True},
                    {"seite": "Übertragungsprotokoll", "wert": "48.000 EUR", "ok": True},
                ],
            },
            {
                "z": "5",
                "e": "E0100002",
                "bez": "Einbehaltene Lohnsteuer",
                "einheit": "EUR",
                "art": "betrag",
                "wert": "7.320,00",
                "belegstand": "belegt",
                "proben": [
                    {
                        "seite": "Übertragungsprotokoll",
                        "wert": "7.300 EUR",
                        "ok": False,
                        "text": "Der Betrag im Protokoll weicht um 20 EUR ab.",
                    }
                ],
            },
            {
                "z": "6",
                "e": "E0100003",
                "bez": "Solidaritätszuschlag",
                "einheit": "EUR",
                "art": "entfaellt",
                "grund": "Freigrenze nicht überschritten laut Lohnsteuerbescheinigung",
                "proben": [],
            },
        ],
    ),
    (
        "Werbungskosten",
        [
            {
                "z": "31",
                "e": "E0107101",
                "bez": "Entfernungspauschale",
                "einheit": "EUR",
                "art": "offen",
                "grund": "Es fehlt die Erste Tätigkeitsstätte im Modul Arbeit.",
                "proben": [],
            },
            {
                "z": "36",
                "e": "E0107301",
                "bez": "Arbeitsmittel",
                "einheit": "EUR",
                "art": "betrag",
                "wert": "215",
                "belegstand": "angenommen",
                "proben": [],
            },
            {
                "z": "41",
                "e": "E0107501",
                "bez": "Zeitraum der Tätigkeit an anderen Orten",
                "einheit": "TT.MM-TT.MM",
                "art": "eingabe",
                "wert": "02.01-30.06",
                "proben": [],
            },
        ],
    ),
]
ANLAGEN = [
    {
        "name": "Anlage N",
        "seiten": ["Arbeitslohn und Werbungskosten", "Reisekosten"],
        "offen": True,
    },
    {"name": "Anlage Vorsorgeaufwand", "seiten": ["Beiträge"], "offen": False},
    {"name": "Anlage Sonderausgaben", "seiten": ["Kirchensteuer", "Spenden"], "offen": False},
]
SEITE = [
    ("Belege", "/belege", "file-text", 4),
    ("Steuerjahr", "/steuerjahr", "list-checks", 0),
    ("Arbeit", "/belege", "car", 0),
    ("Aussteller", "/belege", "user-round", 0),
]
ROUTES = {"/belege": "belege.html", "/steuerjahr": "anlage.html", "/app-icon": "app_icon.html"}


def render(path: str, query: dict[str, list[str]]) -> bytes | None:
    template = ROUTES.get(path)
    if template is None:
        return None

    def pick(key: str, allowed, default: str) -> str:
        value = query.get(key, [default])[0]
        return value if value in allowed else default

    state = {
        "v": pick("v", VARIANTS, "a"),
        "i": pick("i", APP_ICONS, "1"),
        "d": pick("d", {"system", "hell", "dunkel"}, "system"),
    }

    def link(target: str | None = None, **change: str) -> str:
        return (target or path) + "?" + urlencode({**state, **change})

    return (
        env.get_template(template)
        .render(
            **state,
            link=link,
            path=path,
            varianten=VARIANTS,
            app_icons=APP_ICONS,
            neu=NEU,
            erwartet=ERWARTET,
            aufgenommen=AUFGENOMMEN,
            abschnitte=ABSCHNITTE,
            anlagen=ANLAGEN,
            seite=SEITE,
            jahr=2025,
        )
        .encode()
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/":
            self.send_response(302)
            self.send_header("Location", "/belege")
            self.end_headers()
            return
        if url.path.startswith("/static/"):
            target = (STATIC / url.path.removeprefix("/static/")).resolve()
            if STATIC.resolve() in target.parents and target.is_file():
                self.reply(
                    target.read_bytes(), mimetypes.guess_type(target.name)[0] or "text/plain"
                )
                return
        else:
            body = render(url.path, parse_qs(url.query))
            if body is not None:
                self.reply(body, "text/html; charset=utf-8")
                return
        self.send_error(404)

    def reply(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Wie die App: nichts von außen, keine Inline-Stile.
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    print(f"Optik-Prototyp: http://127.0.0.1:{PORT}/  (Strg+C beendet)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
