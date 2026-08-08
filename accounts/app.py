"""Servidor HTTP interno (stdlib). API de cuentas de usuario.

Endpoints:
  GET    /api/health                          — vivo + estado DB (siempre)
  GET    /api/auth/config                     — {enabled, client_id} para el botón
  POST   /api/auth/google                     — {credential} → verifica → sesión → cookie
  POST   /api/auth/logout                     — revoca sesión + borra cookie
  GET    /api/me                              — usuario actual (por cookie) o {ok:false}

  (requieren sesión; 401 si no hay)
  GET    /api/follows                         — favorito + equipos + competiciones
  PUT    /api/follows/favorite-team           — {espn_team_id, league_slug}
  DELETE /api/follows/favorite-team           — quita el favorito
  POST   /api/follows/teams                   — {espn_team_id, league_slug}
  DELETE /api/follows/teams/{espnId}
  POST   /api/follows/competitions/{slug}
  DELETE /api/follows/competitions/{slug}

  DELETE /api/account                         — (CP4) borrado de cuenta

Con ACCOUNTS_ENABLED=false todo (salvo /api/health y /api/auth/config) responde
"disabled". CORS con allowlist solo para dev cross-port; en producción el frontend
comparte origen (Caddy proxya /api/*). Las mutaciones devuelven el estado de
follows completo, para que el frontend se actualice sin otra llamada.
"""

from __future__ import annotations

import json
import logging
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import auth, catalog, config, db, sessions
from .ratelimit import RateLimiter

log = logging.getLogger("accounts.app")

_MAX_BODY = 64 * 1024  # los ID token de Google rondan 1-2 KB; 64 KB es de sobra

# Rate limiter compartido para /api/auth (anti-abuso del login). Por IP de cliente.
_auth_limiter = RateLimiter(config.RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ── helpers de respuesta ──────────────────────────────────────────────────
    def _cors_headers(self):
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
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in self._cors_headers():
            self.send_header(k, v)
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        # El cuerpo ya se leyó entero en _guard (self._raw_body); aquí solo se parsea.
        raw = getattr(self, "_raw_body", b"")
        if not raw:
            return None
        try:
            return json.loads(raw)
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

    def _current_user(self):
        return sessions.user_for_token(self._cookie(config.SESSION_COOKIE))

    def _client_ip(self):
        # Detrás de Cloudflare + Caddy: la IP real llega en cabeceras. (Ojo: el
        # origen es accesible directo, así que estas cabeceras son spoofables si se
        # salta Cloudflare — es defensa en profundidad, no la barrera principal.)
        return (self.headers.get("CF-Connecting-IP")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    # ── verbos ────────────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        extra = [
            ("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"),
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

    def do_PUT(self):
        self._guard(self._route_put)

    def do_DELETE(self):
        self._guard(self._route_delete)

    def _guard(self, fn):
        try:
            # Consume SIEMPRE el cuerpo, aunque la ruta no lo lea. En keep-alive
            # (Caddy reusa la conexión upstream a :8771) los bytes de cuerpo sin
            # leer corromperían la SIGUIENTE petición de esa conexión.
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                self.close_connection = True
                return self._send(400, {"ok": False, "reason": "bad-request"})
            if n > _MAX_BODY:
                self.close_connection = True  # no drenamos cuerpos enormes (DoS)
                return self._send(413, {"ok": False, "reason": "payload-too-large"})
            self._raw_body = self.rfile.read(n) if n > 0 else b""

            path = self.path.split("?", 1)[0].rstrip("/")
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] != "api":
                return self._send(404, {"ok": False, "reason": "not-found"})
            fn(parts[1:])
        except Exception:
            log.exception("error sirviendo %s", self.path)
            self._send(200, {"ok": False, "reason": "internal-error"})

    # ── validación de follows ─────────────────────────────────────────────────
    def _valid_slug(self, slug):
        return bool(slug) and slug in catalog.valid_league_slugs()

    def _valid_team(self, tid, slug):
        # Los ids de equipo de ESPN son numéricos; validamos formato + catálogo de liga.
        return bool(tid) and tid.isdigit() and self._valid_slug(slug)

    def _follows_ok(self, user_id, code=200):
        return self._send(code, {"ok": True, **db.get_follows(user_id)})

    # ── rutas GET ─────────────────────────────────────────────────────────────
    def _route_get(self, rest):
        if rest == ["health"]:
            return self._send(200, {
                "ok": True, "service": "accounts",
                "enabled": config.ACCOUNTS_ENABLED, "db": db.health(),
            })

        if rest == ["auth", "config"]:
            return self._send(200, {
                "ok": True, "enabled": config.ACCOUNTS_ENABLED,
                "client_id": config.GOOGLE_CLIENT_ID if config.ACCOUNTS_ENABLED else "",
            })

        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        if rest == ["me"]:
            user = self._current_user()
            if not user:
                return self._send(200, {"ok": False, "reason": "no-session"})
            return self._send(200, {"ok": True, "user": user})

        if rest == ["follows"]:
            user = self._current_user()
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            return self._follows_ok(user["id"])

        return self._send(404, {"ok": False, "reason": "not-found"})

    # ── rutas POST ────────────────────────────────────────────────────────────
    def _route_post(self, rest):
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        # Rate limit de /api/auth (login/logout) por IP — anti-abuso.
        if rest[:1] == ["auth"] and not _auth_limiter.allow(self._client_ip()):
            return self._send(429, {"ok": False, "reason": "rate-limited"})

        if rest == ["auth", "google"]:
            data = self._read_json() or {}
            try:
                claims = auth.verify_google_id_token(data.get("credential"))
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
            return self._send(200, {"ok": True}, extra_headers=[self._set_session_cookie("", 0)])

        # ── follows (requieren sesión) ──
        user = self._current_user()

        if rest == ["follows", "teams"]:
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            data = self._read_json() or {}
            tid = str(data.get("espn_team_id", "")).strip()
            slug = str(data.get("league_slug", "")).strip()
            name = str(data.get("name", "")).strip()[:80]
            if not self._valid_team(tid, slug):
                return self._send(400, {"ok": False, "reason": "invalid-team"})
            if not db.add_followed_team(user["id"], tid, slug, name, config.MAX_FOLLOWED_TEAMS):
                return self._send(409, {"ok": False, "reason": "limit-reached"})
            return self._follows_ok(user["id"])

        if len(rest) == 3 and rest[:2] == ["follows", "competitions"]:
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            slug = rest[2]
            if not self._valid_slug(slug):
                return self._send(400, {"ok": False, "reason": "invalid-competition"})
            if not db.add_followed_competition(user["id"], slug, config.MAX_FOLLOWED_COMPETITIONS):
                return self._send(409, {"ok": False, "reason": "limit-reached"})
            return self._follows_ok(user["id"])

        return self._send(404, {"ok": False, "reason": "not-found"})

    # ── rutas PUT ─────────────────────────────────────────────────────────────
    def _route_put(self, rest):
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        if rest == ["follows", "favorite-team"]:
            user = self._current_user()
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            data = self._read_json() or {}
            tid = str(data.get("espn_team_id", "")).strip()
            slug = str(data.get("league_slug", "")).strip()
            name = str(data.get("name", "")).strip()[:80]
            if not self._valid_team(tid, slug):
                return self._send(400, {"ok": False, "reason": "invalid-team"})
            db.set_favorite_team(user["id"], tid, slug, name)
            return self._follows_ok(user["id"])

        return self._send(404, {"ok": False, "reason": "not-found"})

    # ── rutas DELETE ──────────────────────────────────────────────────────────
    def _route_delete(self, rest):
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        user = self._current_user()
        if not user:
            return self._send(401, {"ok": False, "reason": "unauthorized"})

        # Borrado de cuenta (RGPD, derecho de supresión). El DELETE del usuario
        # cascada a sesiones y follows (FK ON DELETE CASCADE); se limpia la cookie.
        if rest == ["account"]:
            db.delete_user(user["id"])
            return self._send(200, {"ok": True}, extra_headers=[self._set_session_cookie("", 0)])

        if rest == ["follows", "favorite-team"]:
            db.clear_favorite_team(user["id"])
            return self._follows_ok(user["id"])

        if len(rest) == 3 and rest[:2] == ["follows", "teams"]:
            db.remove_followed_team(user["id"], rest[2])
            return self._follows_ok(user["id"])

        if len(rest) == 3 and rest[:2] == ["follows", "competitions"]:
            db.remove_followed_competition(user["id"], rest[2])
            return self._follows_ok(user["id"])

        return self._send(404, {"ok": False, "reason": "not-found"})


def serve():
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("accounts escuchando en http://%s:%s", config.HOST, config.PORT)
    return httpd
