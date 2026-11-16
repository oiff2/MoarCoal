"""Absicherung des lokalen Servers nach ADR 0007: Host, Origin, CSP."""

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD"})

CONTENT_SECURITY_POLICY = "default-src 'self'; connect-src 'self'; frame-ancestors 'none'"


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def add_security_headers(headers: MutableHeaders) -> None:
    if "Content-Security-Policy" not in headers:  # Vorschau-Antworten bringen eine eigene mit
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    headers["X-Content-Type-Options"] = "nosniff"


class SecurityMiddleware:
    """Weist fremde Hosts und fremde ändernde Anfragen ab, setzt Schutz-Header."""

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.hosts = allowed_hosts(port)
        self.origins = allowed_origins(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rejection = self._reject(Request(scope))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                add_security_headers(MutableHeaders(scope=message))
            await send(message)

        if rejection is not None:
            await rejection(scope, receive, send_with_headers)
            return
        await self.app(scope, receive, send_with_headers)

    def _reject(self, request: Request) -> Response | None:
        if request.headers.get("host") not in self.hosts:
            return PlainTextResponse("Ungültiger Host.", status_code=400)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            same_origin = request.headers.get("sec-fetch-site") == "same-origin"
            if origin not in self.origins and not same_origin:
                return PlainTextResponse("Fremder Ursprung abgewiesen.", status_code=403)
        return None
