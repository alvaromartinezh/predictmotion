"""Servidor HTTP interno (stdlib). API de cuentas de usuario.

CP0 (a oscuras): solo expone /api/health, que confirma que el servicio vive y que
la DB abre. El resto de rutas responden "disabled" mientras ACCOUNTS_ENABLED sea
false; los endpoints reales (auth/me/follows) llegan en CP1/CP2.

Mismo patrón que live_tracker/app.py: BaseHTTPRequestHandler + ThreadingHTTPServer,
respuestas JSON {ok: bool, ...}, sin llamar a nada externo en línea.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db

log = logging.getLogger("accounts.app")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencia el log por petición (usamos logging)
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._route("GET")
        except Exception:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    def do_POST(self):
        try:
            self._route("POST")
        except Exception:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    def do_DELETE(self):
        try:
            self._route("DELETE")
        except Exception:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    def _route(self, method):
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = [p for p in path.split("/") if p]  # ['api', ...]
        if not parts or parts[0] != "api":
            return self._send(404, {"ok": False, "reason": "not-found"})
        rest = parts[1:]

        # /api/health — siempre disponible (incluso con la feature apagada).
        if rest == ["health"] and method == "GET":
            return self._send(200, {
                "ok": True,
                "service": "accounts",
                "enabled": config.ACCOUNTS_ENABLED,
                "db": db.health(),
            })

        # Con la feature apagada, todo lo demás responde "disabled" (a oscuras).
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        # Endpoints reales: CP1 (auth/me) y CP2 (follows). Placeholder por ahora.
        return self._send(501, {"ok": False, "reason": "not-implemented"})


def serve():
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("accounts escuchando en http://%s:%s", config.HOST, config.PORT)
    return httpd
