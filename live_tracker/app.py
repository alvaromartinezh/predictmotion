"""Servidor HTTP interno (stdlib). Expone el proxy normalizado al frontend.

Endpoints:
  GET /api/live/health
  GET /api/live/{league}/matches
  GET /api/live/{league}/match/{id}

Nunca llama a ESPN en línea: sirve desde LiveStore. Si la feature está desactivada
o la fuente falla, responde {ok:false} y el frontend degrada limpio.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .cache import LiveStore

log = logging.getLogger("live_tracker.app")

STORE: LiveStore | None = None  # inyectado por __main__


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencia el log por petición (usamos logging)
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")  # dev cross-port; en prod mismo origen
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._route()
        except Exception as e:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    def _route(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = [p for p in path.split("/") if p]   # ['api','live',...]
        if parts[:2] != ["api", "live"]:
            return self._send(404, {"ok": False, "reason": "not-found"})
        rest = parts[2:]

        if rest == ["health"]:
            return self._send(200, {"ok": True, "enabled": config.LIVE_TRACKING_ENABLED,
                                    "leagues": list(config.LEAGUES.keys())})

        if not config.LIVE_TRACKING_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        # /api/live/{league}/matches
        if len(rest) == 2 and rest[1] == "matches":
            league = rest[0]
            if league not in config.LEAGUES:
                return self._send(404, {"ok": False, "reason": "unknown-league"})
            matches = STORE.get_matches(league) or []
            return self._send(200, {"ok": True, "matches": [m.to_dict() for m in matches]})

        # /api/live/{league}/match/{id}
        if len(rest) == 3 and rest[1] == "match":
            league, eid = rest[0], rest[2]
            if league not in config.LEAGUES:
                return self._send(404, {"ok": False, "reason": "unknown-league"})
            detail = STORE.get_detail(league, eid)
            if detail is None:
                return self._send(200, {"ok": False, "reason": "unavailable"})
            return self._send(200, {"ok": True, "match": detail.to_dict()})

        return self._send(404, {"ok": False, "reason": "not-found"})


def serve(store: LiveStore):
    global STORE
    STORE = store
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("live tracker escuchando en http://%s:%s", config.HOST, config.PORT)
    return httpd
