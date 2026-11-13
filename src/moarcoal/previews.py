"""Vorschau einer Datei eines Ablageorts: Medientyp, Schutz-Header und Antwort.

Gelesen wird nur über `Store.read_site_file` (dessen Pfadregeln gelten). Vorschau gibt es für PDF,
Bilder und HTML; alles andere (auch SVG, das Skript enthalten kann) bekommt keine.
"""

import hashlib
from pathlib import PurePosixPath

from fastapi import HTTPException
from fastapi.responses import Response

from moarcoal.storage import SiteFileError, Store

# Endung -> (Art der Vorschau, Medientyp)
PREVIEWS = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".gif": ("image", "image/gif"),
    ".webp": ("image", "image/webp"),
    ".html": ("html", "text/html; charset=utf-8"),
    ".htm": ("html", "text/html; charset=utf-8"),
}

# Die Datei darf nur von der App selbst eingebettet werden. HTML läuft zusätzlich in einer
# Sandbox ohne Skript, ohne Ursprung und ohne Netz: kein Zugriff auf die App.
FRAME_ONLY_BY_APP = "frame-ancestors 'self'"
HTML_CSP = (
    f"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; {FRAME_ONLY_BY_APP}"
)
IMAGE_CSP = f"default-src 'none'; {FRAME_ONLY_BY_APP}"
CSP_BY_KIND = {"html": HTML_CSP, "image": IMAGE_CSP, "pdf": FRAME_ONLY_BY_APP}


def preview_kind(path: str) -> str | None:
    """`pdf`, `image` oder `html`; ohne Vorschau `None`."""
    entry = PREVIEWS.get(PurePosixPath(path).suffix.lower())
    return entry[0] if entry else None


def file_response(store: Store, site: str, path: str, sha256: str) -> Response:
    """Der Inhalt der Datei als Antwort; 404, wenn sie fehlt, unlesbar oder geändert ist."""
    entry = PREVIEWS.get(PurePosixPath(path).suffix.lower())
    if entry is None:
        raise HTTPException(415, "Für diese Datei gibt es keine Vorschau.")
    try:
        content = store.read_site_file(site, path)
    except SiteFileError:
        raise HTTPException(404) from None
    if hashlib.sha256(content).hexdigest() != sha256:
        raise HTTPException(404)
    kind, media_type = entry
    headers = {"Content-Security-Policy": CSP_BY_KIND[kind], "Content-Disposition": "inline"}
    return Response(content, media_type=media_type, headers=headers)
