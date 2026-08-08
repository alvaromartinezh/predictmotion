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
    league_slug  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followed_teams (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    espn_team_id TEXT NOT NULL,
    league_slug  TEXT NOT NULL,
    PRIMARY KEY (user_id, espn_team_id)
);
CREATE INDEX IF NOT EXISTS idx_followed_teams_user ON followed_teams(user_id);

CREATE TABLE IF NOT EXISTS followed_competitions (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    league_slug TEXT NOT NULL,
    PRIMARY KEY (user_id, league_slug)
);
CREATE INDEX IF NOT EXISTS idx_followed_comps_user ON followed_competitions(user_id);
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
    log.info("DB lista en %s", config.DB_PATH)


def health() -> dict:
    """Comprobación ligera para /api/health: la DB abre y responde una consulta."""
    try:
        with connect() as conn:
            n = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        return {"ok": True, "users": int(n)}
    except Exception as e:  # noqa: BLE001 — health nunca debe lanzar
        log.warning("health de DB falló: %s", e)
        return {"ok": False, "error": type(e).__name__}
