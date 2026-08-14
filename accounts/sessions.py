"""Sesiones de usuario — token opaco en SQLite + cookie.

Tras verificar el ID token de Google (auth.py) NO reutilizamos ese JWT como
sesión (caduca ~1h y no es revocable). Emitimos una sesión propia:
  - token = secrets.token_urlsafe(32) (opaco, aleatorio).
  - En la DB se guarda SOLO el hash SHA-256 del token (si se filtra la DB, no se
    pueden reconstruir cookies válidas).
  - Cookie HttpOnly; Secure; SameSite=Lax con el token en claro (la maneja app.py).

Expiración deslizante suave: al validar, si a la sesión le queda menos de la mitad
del TTL, se extiende. Así el usuario activo no caduca, con como mucho una
escritura por sesión y día.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from . import config, db


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, user_agent: str | None = None) -> str:
    """Crea una sesión para el usuario y devuelve el token en claro (para la cookie)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=config.SESSION_TTL_DAYS)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, user_agent)"
            " VALUES(?,?,?,?,?)",
            (_hash(token), user_id, _iso(now), _iso(expires), (user_agent or "")[:300]),
        )
    return token


def user_for_token(token: str | None) -> dict | None:
    """Valida el token de sesión y devuelve el usuario, o None si no vale/caducó."""
    if not token:
        return None
    th = _hash(token)
    now = _now()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT s.expires_at, u.id, u.email, u.name, u.picture_url"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ?",
            (th,),
        ).fetchone()
        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            expires = now  # dato corrupto → trátalo como caducado
        if expires <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
            return None
        # Expiración deslizante: si queda menos de medio TTL, extiende.
        half = timedelta(days=config.SESSION_TTL_DAYS / 2)
        renewed = expires - now < half
        if renewed:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (_iso(now + timedelta(days=config.SESSION_TTL_DAYS)), th),
            )
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "picture": row["picture_url"],
        # Extender la fila no bastaba: sin reemitir la cookie, el navegador la tira
        # igual al cumplirse su Max-Age. Quien llama (app._current_user) la reemite
        # y quita esta marca antes de serializar el usuario.
        "renewed": renewed,
    }


def destroy_session(token: str | None) -> None:
    """Revoca (borra) la sesión del token. Idempotente."""
    if not token:
        return
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def cleanup_expired() -> int:
    """Borra sesiones caducadas. Devuelve cuántas. Para el cron de limpieza (CP3)."""
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(_now()),))
        return cur.rowcount
