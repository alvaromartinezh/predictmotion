"""Configuración del servicio de cuentas.

Solo stdlib. Todo lo que varía por entorno se lee de variables de entorno (con
defaults seguros), igual que en live_tracker/config.py. Las credenciales reales
(Client ID de Google, etc.) NO viven aquí: se leen del entorno / .env.
"""

import os
from pathlib import Path


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
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ACCOUNTS_DATA_DIR", ROOT / "user_data"))
DB_PATH = Path(os.environ.get("ACCOUNTS_DB_PATH", DATA_DIR / "predictmotion.db"))

# ── Google Sign-In (se usa en CP1) ────────────────────────────────────────────
# Client ID público (puede ir en el JS del frontend). Sin client_secret: el flujo
# de identidad pura solo necesita el Client ID + verificar la firma del ID token.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# ── Sesiones (se usan en CP1) ─────────────────────────────────────────────────
SESSION_COOKIE = os.environ.get("ACCOUNTS_SESSION_COOKIE", "pm_session")
SESSION_TTL_DAYS = _int("ACCOUNTS_SESSION_TTL_DAYS", 30)
# Secure=true en producción (HTTPS). En dev local (http) se puede poner a false.
SESSION_COOKIE_SECURE = _flag("ACCOUNTS_COOKIE_SECURE", True)
