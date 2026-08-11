"""Capa de datos — SQLite (stdlib `sqlite3`). Única capa que toca SQL.

Diseño:
  - Un solo fichero en user_data/ (gitignored). Un solo proceso escritor (este
    servicio) → sin contención multiproceso.
  - Modo WAL: lecturas concurrentes sin bloquear + backup en caliente (.backup()).
  - Esquema idempotente (CREATE TABLE IF NOT EXISTS): init_db() se puede llamar en
    cada arranque sin migraciones para el esquema base.
  - Todas las consultas del resto del código van PARAMETRIZADAS (nunca f-strings
    con datos de usuario).

El esquema completo (users/sessions/follows) se crea ya en CP0 aunque los
endpoints que lo usan lleguen en CP1/CP2: crearlo ahora evita migraciones luego y
no tiene coste.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from . import config

log = logging.getLogger("accounts.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub    TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL,
    name          TEXT,
    picture_url   TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Equipo favorito: uno solo por usuario (PK = user_id).
CREATE TABLE IF NOT EXISTS favorite_team (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    espn_team_id TEXT NOT NULL,
    league_slug  TEXT NOT NULL,
    name         TEXT
);

CREATE TABLE IF NOT EXISTS followed_teams (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    espn_team_id TEXT NOT NULL,
    league_slug  TEXT NOT NULL,
    name         TEXT,
    PRIMARY KEY (user_id, espn_team_id)
);
CREATE INDEX IF NOT EXISTS idx_followed_teams_user ON followed_teams(user_id);

CREATE TABLE IF NOT EXISTS followed_competitions (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    league_slug TEXT NOT NULL,
    PRIMARY KEY (user_id, league_slug)
);
CREATE INDEX IF NOT EXISTS idx_followed_comps_user ON followed_competitions(user_id);

-- Preferencias sueltas del usuario (una fila por usuario, se amplía con columnas
-- según haga falta). Por ahora solo el tema de color del patrón de fondo.
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id  INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bg_theme TEXT
);
"""


def connect() -> sqlite3.Connection:
    """Abre una conexión a la DB con los PRAGMAs del proyecto.

    Crea el directorio user_data/ si no existe. WAL + foreign_keys ON. `row_factory`
    a sqlite3.Row para acceder por nombre de columna.
    """
    path: Path = config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Crea el esquema si no existe. Idempotente; seguro en cada arranque."""
    with connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
    log.info("DB lista en %s", config.DB_PATH)


def _migrate(conn) -> None:
    """Migraciones idempotentes de columnas nuevas sobre tablas ya existentes."""
    # `name` en las tablas de equipos (para mostrar el equipo sin llamar a ESPN).
    for table in ("favorite_team", "followed_teams"):  # nombres fijos, no user input
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "name" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN name TEXT")


def upsert_user(google_sub: str, email: str, name: str | None, picture_url: str | None) -> dict:
    """Crea o actualiza el usuario por su `google_sub` (id estable de Google).

    Actualiza email/nombre/foto y last_login_at en cada login. Devuelve el usuario.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO users(google_sub, email, name, picture_url, created_at, last_login_at)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(google_sub) DO UPDATE SET"
            "   email=excluded.email, name=excluded.name,"
            "   picture_url=excluded.picture_url, last_login_at=excluded.last_login_at",
            (google_sub, email, name, picture_url, now, now),
        )
        row = conn.execute(
            "SELECT id, email, name, picture_url FROM users WHERE google_sub=?",
            (google_sub,),
        ).fetchone()
    return {"id": row["id"], "email": row["email"], "name": row["name"], "picture": row["picture_url"]}


# ── Follows (equipo favorito, equipos y competiciones seguidas) ───────────────
def get_follows(user_id: int) -> dict:
    """Devuelve el estado de follows del usuario: favorito + equipos + competiciones."""
    with connect() as conn:
        fav = conn.execute(
            "SELECT espn_team_id, league_slug, name FROM favorite_team WHERE user_id=?",
            (user_id,),
        ).fetchone()
        teams = conn.execute(
            "SELECT espn_team_id, league_slug, name FROM followed_teams WHERE user_id=? ORDER BY rowid",
            (user_id,),
        ).fetchall()
        comps = conn.execute(
            "SELECT league_slug FROM followed_competitions WHERE user_id=? ORDER BY rowid",
            (user_id,),
        ).fetchall()
    return {
        "favorite_team": ({"espn_team_id": fav["espn_team_id"], "league_slug": fav["league_slug"],
                           "name": fav["name"]} if fav else None),
        "teams": [{"espn_team_id": r["espn_team_id"], "league_slug": r["league_slug"],
                   "name": r["name"]} for r in teams],
        "competitions": [r["league_slug"] for r in comps],
    }


def set_favorite_team(user_id: int, espn_team_id: str, league_slug: str, name: str = "") -> None:
    """Fija el equipo favorito (uno solo por usuario; upsert)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO favorite_team(user_id, espn_team_id, league_slug, name) VALUES(?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   espn_team_id=excluded.espn_team_id, league_slug=excluded.league_slug, name=excluded.name",
            (user_id, espn_team_id, league_slug, name),
        )


def clear_favorite_team(user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM favorite_team WHERE user_id=?", (user_id,))


def add_followed_team(user_id: int, espn_team_id: str, league_slug: str, name: str, cap: int) -> bool:
    """Sigue un equipo. Devuelve False si se alcanzó el tope (y el equipo es nuevo)."""
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM followed_teams WHERE user_id=? AND espn_team_id=?",
            (user_id, espn_team_id),
        ).fetchone()
        if not exists:
            n = conn.execute(
                "SELECT count(*) FROM followed_teams WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            if n >= cap:
                return False
        conn.execute(
            "INSERT INTO followed_teams(user_id, espn_team_id, league_slug, name) VALUES(?,?,?,?)"
            " ON CONFLICT(user_id, espn_team_id) DO UPDATE SET"
            "   league_slug=excluded.league_slug, name=excluded.name",
            (user_id, espn_team_id, league_slug, name),
        )
    return True


def remove_followed_team(user_id: int, espn_team_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM followed_teams WHERE user_id=? AND espn_team_id=?",
            (user_id, espn_team_id),
        )


def add_followed_competition(user_id: int, league_slug: str, cap: int) -> bool:
    """Sigue una competición. Devuelve False si se alcanzó el tope (y es nueva)."""
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM followed_competitions WHERE user_id=? AND league_slug=?",
            (user_id, league_slug),
        ).fetchone()
        if not exists:
            n = conn.execute(
                "SELECT count(*) FROM followed_competitions WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            if n >= cap:
                return False
            conn.execute(
                "INSERT INTO followed_competitions(user_id, league_slug) VALUES(?,?)",
                (user_id, league_slug),
            )
    return True


def remove_followed_competition(user_id: int, league_slug: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM followed_competitions WHERE user_id=? AND league_slug=?",
            (user_id, league_slug),
        )


# ── Preferencias ───────────────────────────────────────────────────────────────
def get_prefs(user_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT bg_theme FROM user_prefs WHERE user_id=?", (user_id,)
        ).fetchone()
    return {"bg_theme": row["bg_theme"] if row else None}


def set_bg_theme(user_id: int, bg_theme: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO user_prefs(user_id, bg_theme) VALUES(?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET bg_theme=excluded.bg_theme",
            (user_id, bg_theme),
        )


def delete_user(user_id: int) -> None:
    """Borra el usuario y, por FK ON DELETE CASCADE, sus sesiones y follows.

    La cascada requiere PRAGMA foreign_keys=ON (lo pone connect()).
    """
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def health() -> dict:
    """Comprobación ligera para /api/health: la DB abre y responde una consulta."""
    try:
        with connect() as conn:
            n = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        return {"ok": True, "users": int(n)}
    except Exception as e:  # noqa: BLE001 — health nunca debe lanzar
        log.warning("health de DB falló: %s", e)
        return {"ok": False, "error": type(e).__name__}
