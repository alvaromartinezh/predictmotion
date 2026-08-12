"""Configuración del servicio de cuentas.

Solo stdlib. Todo lo que varía por entorno se lee de variables de entorno (con
defaults seguros), igual que en live_tracker/config.py. Las credenciales reales
(Client ID de Google, etc.) NO viven aquí: se leen del entorno / .env.

Carga ROOT/.env (gitignored, solo en el servidor) al importar, sin pisar
variables ya definidas en el entorno (systemd Environment= o el shell ganan).
Mismo mini-parser que seo/notify.py, replicado aquí para que accounts sea
autónomo (no dependa de seo).
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = ROOT / ".env"


def _load_env():
    """Carga ROOT/.env en os.environ sin pisar lo ya definido. Sin dependencias."""
    try:
        text = _ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env()


def _flag(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Interruptor general de la feature ─────────────────────────────────────────
# Por defecto DESACTIVADO ("a oscuras"): el servicio arranca, inicializa la DB y
# responde /api/health, pero los endpoints públicos (auth/follows) responden
# "disabled". Se enciende con ACCOUNTS_ENABLED=true cuando la feature esté lista.
ACCOUNTS_ENABLED = _flag("ACCOUNTS_ENABLED", False)

# ── Servidor ──────────────────────────────────────────────────────────────────
PORT = _int("ACCOUNTS_PORT", 8771)
HOST = os.environ.get("ACCOUNTS_HOST", "127.0.0.1")

# ── Almacenamiento ────────────────────────────────────────────────────────────
# Datos de usuarios reales (NO recalculables desde ESPN). Viven en user_data/,
# gitignored, SOLO en el servidor. El git pull del auto-deploy nunca los toca.
DATA_DIR = Path(os.environ.get("ACCOUNTS_DATA_DIR", ROOT / "user_data"))
DB_PATH = Path(os.environ.get("ACCOUNTS_DB_PATH", DATA_DIR / "predictmotion.db"))

# ── Google Sign-In ────────────────────────────────────────────────────────────
# Client ID público (puede ir en el JS del frontend). Sin client_secret: el flujo
# de identidad pura solo necesita el Client ID + verificar la firma del ID token.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# Claves públicas de Google (JWKS) para verificar la firma del ID token en local.
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Emisores válidos del ID token de Google.
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
# Margen de reloj (segundos) al validar exp/iat.
TOKEN_LEEWAY_SECONDS = _int("ACCOUNTS_TOKEN_LEEWAY", 60)

# ── Sesiones ──────────────────────────────────────────────────────────────────
SESSION_COOKIE = os.environ.get("ACCOUNTS_SESSION_COOKIE", "pm_session")
SESSION_TTL_DAYS = _int("ACCOUNTS_SESSION_TTL_DAYS", 30)
# Secure=true en producción (HTTPS). En dev local (http) se pone a false para que
# el navegador acepte la cookie (start.py --accounts lo hace).
SESSION_COOKIE_SECURE = _flag("ACCOUNTS_COOKIE_SECURE", True)

# ── Rate limiting de /api/auth (defensa en profundidad) ───────────────────────
RATE_LIMIT_MAX = _int("ACCOUNTS_RATE_MAX", 20)          # peticiones por ventana e IP
RATE_LIMIT_WINDOW = _int("ACCOUNTS_RATE_WINDOW", 300)   # ventana en segundos (5 min)

# ── Follows (límites de robustez) ─────────────────────────────────────────────
# Topes por usuario para que nadie pueda inflar la DB. Holgados para uso normal.
MAX_FOLLOWED_TEAMS = _int("ACCOUNTS_MAX_TEAMS", 100)
MAX_FOLLOWED_COMPETITIONS = _int("ACCOUNTS_MAX_COMPETITIONS", 30)  # solo existen 15

# ── Preferencias (tema de fondo del shell) ────────────────────────────────────
# Mismo set que BG_THEMES en theme.js (front) — duplicado a propósito, mismo
# patrón que LEAGUES en pm-leagues.js vs seo/config.py (ver CLAUDE.md).
BG_THEMES = ("purple", "green", "blue", "orange", "teal", "rose")

# ── Live tracker (solo lectura) ───────────────────────────────────────────────
# El servicio de votos consulta al live_tracker (mismo host, :8770) si un partido
# ya empezó/terminó, para bloquear el voto server-side. Best-effort: si no responde,
# se permite (el frontend ya gatea por estado).
LIVE_TRACKER_PORT = _int("ACCOUNTS_LIVE_TRACKER_PORT", 8770)

# ── CORS ──────────────────────────────────────────────────────────────────────
# En producción el frontend y la API comparten origen (predictmotion.com, Caddy
# proxya /api/*) → CORS irrelevante. Solo hace falta en dev cross-port
# (localhost:8765 → :8771). Allowlist para poder mandar cookies con credenciales
# (Access-Control-Allow-Credentials no admite '*').
ALLOWED_ORIGINS = {
    "https://predictmotion.com",
    "https://www.predictmotion.com",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
}
