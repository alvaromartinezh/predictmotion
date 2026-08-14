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
  GET    /api/prefs                           — preferencias (tema de fondo)
  PUT    /api/prefs                           — {bg_theme}

  (requieren sesión; 401 si no hay)
  GET    /api/votes?league=&event=            — voto del usuario + conteos 1/X/2
  POST   /api/votes                           — {league, event, pick} registra/cambia voto

  DELETE /api/account                         — (CP4) borrado de cuenta

Con ACCOUNTS_ENABLED=false todo (salvo /api/health y /api/auth/config) responde
"disabled". CORS con allowlist solo para dev cross-port; en producción el frontend
comparte origen (Caddy proxya /api/*). Las mutaciones devuelven el estado de
follows completo, para que el frontend se actualice sin otra llamada.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
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
        for k, v in getattr(self, "_renew_cookie", []):
            self.send_header(k, v)
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
            data = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        # Solo objetos: `json.loads("[1]")` es truthy, así que el `or {}` de los
        # llamadores no saltaba y el .get() siguiente lanzaba AttributeError.
        return data if isinstance(data, dict) else None

    def _read_form(self):
        # Cuerpo application/x-www-form-urlencoded (POST de formulario top-level del
        # login). parse_qs devuelve listas; colapsamos a valor único cuando haya uno.
        raw = getattr(self, "_raw_body", b"")
        if not raw:
            return {}
        try:
            parsed = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 — formulario malformado → trátalo vacío
            return {}
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    def _login_next(self, data):
        """Destino post-login (campo `next` del formulario), SIEMPRE como ruta relativa.

        Este valor va a una cabecera `Location`, así que es entrada hostil:
        - `send_header` de CPython NO sanea CRLF, así que un `next` con %0d%0a
          inyectaba cabeceras enteras en la respuesta (p. ej. un `Set-Cookie` con
          la sesión que quisiera el atacante). Y era alcanzable SIN credencial
          válida, porque la rama de token inválido también redirige aquí.
        - `/\\evil.com` se colaba por la guarda anti open-redirect: el navegador
          normaliza `\\` a `/` y acaba en http://evil.com.
        Por eso: se rechaza cualquier carácter de control, de un origen propio se
        conserva SOLO la ruta (así `http://localhost:8765/x`, que está en la
        allowlist por el dev cross-port, no sirve como destino externo en
        producción) y lo que se devuelve es siempre una ruta relativa.
        """
        nxt = (data or {}).get("next", "/cuenta")
        if isinstance(nxt, (list, tuple)):
            nxt = nxt[0] if nxt else "/cuenta"
        nxt = str(nxt)
        if any(c < " " or c == "\x7f" for c in nxt):
            return "/cuenta"
        for origin in config.ALLOWED_ORIGINS:
            if nxt == origin or nxt.startswith(origin + "/"):
                nxt = nxt[len(origin):] or "/"
                break
        if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
            return nxt
        return "/cuenta"

    def _redirect(self, location, code=303, extra_headers=None):
        # Navegación top-level (login por formulario): sin body, con Location.
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for k, v in getattr(self, "_renew_cookie", []):
            self.send_header(k, v)
        for k, v in self._cors_headers():
            self.send_header(k, v)
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()

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
        # Devuelve DOS cookies: (1) la sesión real HttpOnly (secreto, ilegible por JS)
        # y (2) un "hint" pm_auth=1 SIN HttpOnly, legible por JS, que el shell usa para
        # elegir el primer paint (logueado/anónimo) sin esperar a /api/me y evitar el
        # flash. No lleva secreto: solo marca "hay sesión probable"; /api/me manda.
        common = ["Path=/", "SameSite=Lax", f"Max-Age={max_age}"]
        secure = ["Secure"] if config.SESSION_COOKIE_SECURE else []
        session = [f"{config.SESSION_COOKIE}={token}", "HttpOnly"] + common + secure
        hint = [f"pm_auth={'1' if token else ''}"] + common + secure
        return [("Set-Cookie", "; ".join(session)), ("Set-Cookie", "; ".join(hint))]

    def _current_user(self):
        # La expiración deslizante extendía la fila de `sessions` pero NO reemitía
        # la cookie, así que el navegador la tiraba a los 30 días igual y el usuario
        # activo acababa deslogueado (y quedaba una fila viva que nadie podía
        # presentar). Cuando la sesión se renueva, se reemite aquí; _send/_redirect
        # las ponen ANTES de sus propias cabeceras, para que un login/logout
        # explícito siga mandando.
        token = self._cookie(config.SESSION_COOKIE)
        user = sessions.user_for_token(token)
        if user and user.pop("renewed", False):
            self._renew_cookie = self._set_session_cookie(
                token, config.SESSION_TTL_DAYS * 86400)
        return user

    def _client_ip(self):
        # Detrás de Cloudflare + Caddy: la IP real llega en cabeceras. (Ojo: el
        # origen es accesible directo, así que estas cabeceras son spoofables si se
        # salta Cloudflare — es defensa en profundidad, no la barrera principal.)
        return (self.headers.get("CF-Connecting-IP")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    # ── verbos ────────────────────────────────────────────────────────────────
    def _drain_body(self):
        """Consume el cuerpo entero. Devuelve una respuesta de error o None.

        En keep-alive (Caddy reusa la conexión upstream a :8771) los bytes de
        cuerpo sin leer se parsean como la SIGUIENTE petición de esa conexión, así
        que una petición puede corromper la de otro usuario. El drenaje por
        Content-Length dejaba dos huecos: un cuerpo `chunked` (Content-Length
        ausente → se leía 0) y `do_OPTIONS`, que respondía sin pasar por aquí.
        Un cuerpo chunked no lo manda ningún cliente nuestro, así que se rechaza y
        se cierra la conexión en vez de implementar el desencuadrado.
        """
        if (self.headers.get("Transfer-Encoding") or "").strip():
            self.close_connection = True
            return self._send(400, {"ok": False, "reason": "bad-request"})
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            self.close_connection = True
            return self._send(400, {"ok": False, "reason": "bad-request"})
        if n > _MAX_BODY:
            self.close_connection = True  # no drenamos cuerpos enormes (DoS)
            return self._send(413, {"ok": False, "reason": "payload-too-large"})
        self._raw_body = self.rfile.read(n) if n > 0 else b""
        return None

    def do_OPTIONS(self):
        if self._drain_body() is not None:
            return
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
            if self._drain_body() is not None:   # cuerpo consumido SIEMPRE
                return

            path = self.path.split("?", 1)[0].rstrip("/")
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] != "api":
                return self._send(404, {"ok": False, "reason": "not-found"})
            fn(parts[1:])
        except Exception:
            # 500, no 200: con 200 un endpoint que fallara siempre (DB bloqueada,
            # disco lleno) no aparecía como error en NINGÚN log — el mismo patrón
            # de fallo silencioso contra el que este proyecto monta alertas. El
            # cliente no se entera del cambio: assets/account.js solo mira `ok`.
            log.exception("error sirviendo %s", self.path)
            self._send(500, {"ok": False, "reason": "internal-error"})

    # ── validación de follows ─────────────────────────────────────────────────
    def _valid_slug(self, slug):
        return bool(slug) and slug in catalog.valid_league_slugs()

    def _valid_team(self, tid, slug):
        # Los ids de equipo de ESPN son numéricos ASCII; validamos formato + catálogo.
        # `isdigit()` a secas acepta dígitos Unicode ('٣', '²'), que se guardaban como
        # equipo seguido y luego no resolvían contra ninguna URL de ESPN.
        return bool(tid) and len(tid) <= 12 and tid.isascii() and tid.isdigit() \
            and self._valid_slug(slug)

    def _follows_ok(self, user_id, code=200):
        return self._send(code, {"ok": True, **db.get_follows(user_id)})

    # ── votos 1X2 ─────────────────────────────────────────────────────────────
    def _vote_ok(self, user_id, league, event_id, code=200):
        mine = db.get_user_vote(user_id, league, event_id)
        counts = db.get_match_votes(league, event_id)
        return self._send(code, {"ok": True, "mine": mine, **counts})

    def _valid_match(self, league, event_id):
        # El id de evento de ESPN es numérico. Antes valía cualquier cadena no
        # vacía (hasta el tope de 64 KB del cuerpo), y como la PK es
        # (user_id, league, event_id) se podían insertar filas sin fin.
        return (bool(league) and self._valid_slug(league)
                and bool(event_id) and len(event_id) <= 20
                and event_id.isascii() and event_id.isdigit())

    def _match_votable(self, league, event_id):
        """¿Se puede votar este partido? Best-effort contra el live_tracker.

        La regla de producto es: votar SOLO mientras el partido está en 'pre'
        (antes del pitido inicial). El frontend ya la aplica con el estado que le
        llega; aquí se revalida server-side consultando al live_tracker (mismo
        host, localhost). Si el live_tracker no responde o no conoce el partido,
        se PERMITE votar (defensa en profundidad, no barrera única): no queremos
        que una caída del tracker tumbe la votación de partidos sin empezar.
        """
        try:
            url = ("http://127.0.0.1:%d/api/live/%s/match/%s" % (
                config.LIVE_TRACKER_PORT,
                urllib.parse.quote(league, safe=""),
                urllib.parse.quote(event_id, safe=""),
            ))
            with urllib.request.urlopen(url, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
            if not data.get("ok"):
                return True  # no lo conoce → sin información, se permite
            state = ((data.get("match") or {}).get("status") or {}).get("state")
            return state == "pre"
        except Exception:  # noqa: BLE001 — best-effort: timeout/caída → permitir
            log.info("live_tracker no respondió al validar el voto (%s/%s)", league, event_id)
            return True

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

        if rest == ["prefs"]:
            user = self._current_user()
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            return self._send(200, {"ok": True, **db.get_prefs(user["id"])})

        if rest == ["votes"]:
            user = self._current_user()
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            query = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            league = (query.get("league") or [""])[0]
            event = (query.get("event") or [""])[0]
            if not self._valid_match(league, event):
                return self._send(400, {"ok": False, "reason": "invalid-match"})
            return self._vote_ok(user["id"], league, event)

        return self._send(404, {"ok": False, "reason": "not-found"})

    # ── rutas POST ────────────────────────────────────────────────────────────
    def _route_post(self, rest):
        if not config.ACCOUNTS_ENABLED:
            return self._send(503, {"ok": False, "reason": "disabled"})

        # Rate limit de /api/auth (login/logout) por IP — anti-abuso.
        if rest[:1] == ["auth"] and not _auth_limiter.allow(self._client_ip()):
            return self._send(429, {"ok": False, "reason": "rate-limited"})

        if rest == ["auth", "google"]:
            # Dos modos: (1) form POST top-level (login del navegador) → 303 con
            # Set-Cookie, para que la cookie de sesión se commitee SIEMPRE (móvil
            # incluido; un fetch XHR la pierde a veces); (2) fetch JSON (dev/tests)
            # → 200 con Set-Cookie. La verificación es idéntica.
            # El formulario de login lo construye NUESTRA página (cuenta.html), así
            # que su Origin es propio. Una página atacante que auto-envíe el mismo
            # formulario con SU credential logueaba a la víctima en la cuenta del
            # atacante, y a partir de ahí sus follows, prefs y votos se escribían
            # ahí. Se rechaza cuando el Origin viene y NO es nuestro; si no viene
            # (navegadores que lo omiten en same-origin) no se bloquea, porque un
            # POST cross-site sí lo lleva siempre.
            origin = self.headers.get("Origin")
            if origin and origin not in config.ALLOWED_ORIGINS:
                log.info("login rechazado: Origin ajeno %s", origin)
                return self._send(403, {"ok": False, "reason": "forbidden-origin"})

            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            form = ctype == "application/x-www-form-urlencoded"
            data = self._read_form() if form else (self._read_json() or {})
            try:
                claims = auth.verify_google_id_token(data.get("credential"))
            except auth.TokenError as e:
                log.info("login rechazado: %s", e)
                if form:
                    loc = self._login_next(data)
                    if "?" in loc:
                        loc += "&login=error"
                    else:
                        loc += "?login=error"
                    return self._redirect(loc)
                return self._send(401, {"ok": False, "reason": "invalid-token"})
            user = db.upsert_user(
                google_sub=claims["sub"],
                email=claims.get("email", ""),
                name=claims.get("name"),
                picture_url=claims.get("picture"),
            )
            token = sessions.create_session(user["id"], self.headers.get("User-Agent"))
            cookies = self._set_session_cookie(token, config.SESSION_TTL_DAYS * 86400)
            if form:
                return self._redirect(self._login_next(data), 303, cookies)
            return self._send(200, {"ok": True, "user": user}, extra_headers=cookies)

        if rest == ["auth", "logout"]:
            sessions.destroy_session(self._cookie(config.SESSION_COOKIE))
            return self._send(200, {"ok": True}, extra_headers=self._set_session_cookie("", 0))

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

        # ── votos 1X2 (requieren sesión) ──
        if rest == ["votes"]:
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            data = self._read_json() or {}
            league = str(data.get("league", "")).strip()
            event = str(data.get("event", "")).strip()
            pick = str(data.get("pick", "")).strip().upper()
            if not self._valid_match(league, event) or pick not in ("1", "X", "2"):
                return self._send(400, {"ok": False, "reason": "invalid-vote"})
            if not self._match_votable(league, event):
                return self._send(409, {"ok": False, "reason": "match-started"})
            if not db.upsert_vote(user["id"], league, event, pick,
                                  config.MAX_VOTES):
                return self._send(409, {"ok": False, "reason": "limit-reached"})
            return self._vote_ok(user["id"], league, event)

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

        if rest == ["prefs"]:
            user = self._current_user()
            if not user:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            data = self._read_json() or {}
            bg_theme = str(data.get("bg_theme", "")).strip()
            if bg_theme not in config.BG_THEMES:
                return self._send(400, {"ok": False, "reason": "invalid-bg-theme"})
            db.set_bg_theme(user["id"], bg_theme)
            return self._send(200, {"ok": True, **db.get_prefs(user["id"])})

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
            return self._send(200, {"ok": True}, extra_headers=self._set_session_cookie("", 0))

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
