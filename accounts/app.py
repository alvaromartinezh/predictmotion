"""Servidor HTTP interno (stdlib). API de cuentas de usuario.

Endpoints (CP1):
  GET  /api/health              — vivo + estado DB (siempre, incluso flag off)
  GET  /api/auth/config         — {enabled, client_id} para inicializar el botón
  POST /api/auth/google         — {credential} → verifica → sesión → set-cookie
  POST /api/auth/logout         — revoca sesión + borra cookie
  GET  /api/me                  — usuario actual (por cookie) o {ok:false}
  (CP2) /api/follows/*, /api/account → 501 por ahora

Mismo patrón que live_tracker/app.py. Con ACCOUNTS_ENABLED=false todo (salvo
/api/health) responde "disabled". CORS con allowlist solo para dev cross-port; en
producción el frontend comparte origen (Caddy proxya /api/*).
"""

from __future__ import annotations

import json
import logging
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import auth, config, db, sessions

log = logging.getLogger("accounts.app")

_MAX_BODY = 64 * 1024  # los ID token de Google rondan 1-2 KB; 64 KB es de sobra


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ── helpers de respuesta ──────────────────────────────────────────────────
    def _cors_headers(self):
        """Headers CORS si el Origin está en la allowlist (dev cross-port)."""
        origin = self.headers.get("Origin")
        if origin and origin in config.ALLOWED_ORIGINS:
            return [
                ("Access-Control-Allow-Origin", origin),
                ("Access-Control-Allow-Credentials", "true"),
                ("Vary", "Origin"),
            ]
        return []

    def _send(self, code, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in self._cors_headers():
            self.send_header(k, v)
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None
        if length <= 0 or length > _MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def _cookie(self, name):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 — cookie malformada
            return None
        m = jar.get(name)
        return m.value if m else None

    def _set_session_cookie(self, token, max_age):
        parts = [f"{config.SESSION_COOKIE}={token}", "Path=/", "HttpOnly",
                 "SameSite=Lax", f"Max-Age={max_age}"]
        if config.SESSION_COOKIE_SECURE:
            parts.append("Secure")
        return ("Set-Cookie", "; ".join(parts))

    # ── verbos ────────────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        # Preflight CORS (POST con application/json lo dispara en dev cross-port).
        extra = [
            ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
            ("Access-Control-Max-Age", "600"),
        ]
        self.send_response(204)
        for k, v in self._cors_headers():
            self.send_header(k, v)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._guard(self._route_get)

    def do_POST(self):
        self._guard(self._route_post)

    def do_DELETE(self):
        self._guard(lambda parts: self._send(501, {"ok": False, "reason": "not-implemented"}))

    def _guard(self, fn):
        try:
            path = self.path.split("?", 1)[0].rstrip("/")
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] != "api":
                return self._send(404, {"ok": False, "reason": "not-found"})
            fn(parts[1:])
        except Exception:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    # ── rutas GET ─────────────────────────────────────────────────────────────
    def _route_get(self, rest):
        if rest == ["health"]:
            return self._send(200, {
                "ok": True, "service": "accounts",
                "enabled": config.ACCOUNTS_ENABLED, "db": db.health(),
            })

        # config del botón: se sirve aunque la feature esté "encendida"; con flag
        # off devolvemos enabled:false y sin client_id (el frontend no pinta botón).
        if rest == ["auth", "config"]:
            return self._send(200, {
                "ok": True, "enabled": config.ACCOUNTS_ENABLED,
                "client_id": config.GOOGLE_CLIENT_ID if config.ACCOUNTS_ENABLED else "",
            })

        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        if rest == ["me"]:
            user = sessions.user_for_token(self._cookie(config.SESSION_COOKIE))
            if not user:
                return self._send(200, {"ok": False, "reason": "no-session"})
            return self._send(200, {"ok": True, "user": user})

        return self._send(404, {"ok": False, "reason": "not-found"})

    # ── rutas POST ────────────────────────────────────────────────────────────
    def _route_post(self, rest):
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        if rest == ["auth", "google"]:
            data = self._read_json() or {}
            credential = data.get("credential")
            try:
                claims = auth.verify_google_id_token(credential)
            except auth.TokenError as e:
                log.info("login rechazado: %s", e)
                return self._send(401, {"ok": False, "reason": "invalid-token"})
            user = db.upsert_user(
                google_sub=claims["sub"],
                email=claims.get("email", ""),
                name=claims.get("name"),
                picture_url=claims.get("picture"),
            )
            token = sessions.create_session(user["id"], self.headers.get("User-Agent"))
            cookie = self._set_session_cookie(token, config.SESSION_TTL_DAYS * 86400)
            return self._send(200, {"ok": True, "user": user}, extra_headers=[cookie])

        if rest == ["auth", "logout"]:
            sessions.destroy_session(self._cookie(config.SESSION_COOKIE))
            cleared = self._set_session_cookie("", 0)
            return self._send(200, {"ok": True}, extra_headers=[cleared])

        return self._send(404, {"ok": False, "reason": "not-found"})


def serve():
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("accounts escuchando en http://%s:%s", config.HOST, config.PORT)
    return httpd
