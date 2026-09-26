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
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .cache import LiveStore

log = logging.getLogger("live_tracker.app")

STORE: LiveStore | None = None  # inyectado por __main__

# Hosts de la API de ESPN que el proxy puede reenviar, con el prefijo de ruta
# permitido por host (whitelist anti-SSRF). site.api.espn.com usa /apis/;
# sports.core.api.espn.com usa /v2/.
_ESPN_PROXY_HOSTS = {
    "site.api.espn.com": "/apis/",
    "sports.core.api.espn.com": "/v2/",
}
_espn_cache: dict[str, tuple[float, int, str, bytes]] = {}

# `scoreboard?dates=AÑO` (año suelto, sin rango): la temporada completa de esa
# liga, ~4-5 MB. Ver comentario de ESPN_PROXY_SEASON_CACHE_TTL en config.py.
_SEASON_QUERY_RE = re.compile(r"[?&]dates=\d{4}(&|$)")


def _cache_ttl(url: str) -> int:
    return (config.ESPN_PROXY_SEASON_CACHE_TTL if _SEASON_QUERY_RE.search(url)
            else config.ESPN_PROXY_CACHE_TTL)


def _espn_fetch(url: str) -> tuple[int, str, bytes, int]:
    """GET a la API de ESPN con el UA por defecto de urllib (sí pasa el 403
    que ESPN/Cloudflare da a los UA de navegador; NO volver a un UA tipo browser)."""
    ttl = _cache_ttl(url)
    now = time.time()
    hit = _espn_cache.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[2], hit[3], ttl
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=config.ESPN_PROXY_TIMEOUT) as r:
        status = r.status
        ctype = r.headers.get("Content-Type", "application/json; charset=utf-8")
        body = r.read()
    _espn_cache[url] = (now, status, ctype, body)
    if len(_espn_cache) > 256:
        _espn_cache.pop(next(iter(_espn_cache)))
    return status, ctype, body, ttl


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

    def _send_raw(self, status, ctype, body, max_age=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # El proxy ya deduplica estas respuestas en su propia caché (TTL en
        # _cache_ttl); dejar que el navegador también las cachee evita que cada
        # visita vuelva a descargar los mismos bytes (hasta ~5 MB en las
        # consultas de temporada completa, ver ESPN_PROXY_SEASON_CACHE_TTL).
        self.send_header("Cache-Control", f"public, max-age={max_age}" if max_age else "no-store")
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

        # /api/espn/<host>/<path...> — proxy genérico a la API de ESPN
        # (fix 2026-08-12: ESPN da 403 a los UA de navegador, que no pueden
        # cambiarse; aquí se reenvía con UA de urllib, que sí pasa).
        if parts[:2] == ["api", "espn"]:
            return self._espn_proxy(parts[2:])

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
            detail = STORE.get_detail(league, eid)  # ya es un dict listo para servir
            if detail is None:
                return self._send(200, {"ok": False, "reason": "unavailable"})
            return self._send(200, {"ok": True, "match": detail})

        return self._send(404, {"ok": False, "reason": "not-found"})

    def _espn_proxy(self, rest):
        if not config.ESPN_PROXY_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})
        if len(rest) < 2:
            return self._send(400, {"ok": False, "reason": "bad-path"})
        host, sub = rest[0], "/" + "/".join(rest[1:])
        prefix = _ESPN_PROXY_HOSTS.get(host)
        if prefix is None:
            return self._send(403, {"ok": False, "reason": "host-not-allowed"})
        if not sub.startswith(prefix):
            return self._send(403, {"ok": False, "reason": "path-not-allowed"})
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        url = "https://" + host + sub + (("?" + query) if query else "")
        try:
            status, ctype, body, max_age = _espn_fetch(url)
        except urllib.error.HTTPError as e:
            status = e.code
            ctype = e.headers.get("Content-Type", "application/json; charset=utf-8")
            body = e.read()
            max_age = None  # error de ESPN: no lo cachee el navegador
        except Exception as e:
            log.warning("proxy ESPN: falló %s: %s", url[:120], e)
            return self._send(502, {"ok": False, "reason": "upstream-error"})
        return self._send_raw(status, ctype, body, max_age)


def serve(store: LiveStore):
    global STORE
    STORE = store
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("live tracker escuchando en http://%s:%s", config.HOST, config.PORT)
    return httpd
