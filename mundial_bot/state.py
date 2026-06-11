"""Persistencia de estado en SQLite: eventos notificados, marcadores, resúmenes diarios."""

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "state.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS notified_events (
            event_type TEXT NOT NULL,
            match_id   TEXT NOT NULL,
            extra      TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (event_type, match_id, extra)
        );
        CREATE TABLE IF NOT EXISTS match_scores (
            match_id   TEXT PRIMARY KEY,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS daily_sent (
            send_date  TEXT NOT NULL,
            send_type  TEXT NOT NULL,
            sent_at    TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (send_date, send_type)
        );
        CREATE TABLE IF NOT EXISTS pending_posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text       TEXT NOT NULL,
            image_path TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',  -- pending|published|failed
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)


def already_notified(event_type: str, match_id: str, extra: str = "") -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM notified_events WHERE event_type=? AND match_id=? AND extra=?",
            (event_type, match_id, extra),
        ).fetchone()
        return row is not None


def mark_notified(event_type: str, match_id: str, extra: str = ""):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notified_events(event_type,match_id,extra) VALUES(?,?,?)",
            (event_type, match_id, extra),
        )


def get_last_score(match_id: str) -> tuple[int, int] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT home_score,away_score FROM match_scores WHERE match_id=?",
            (match_id,),
        ).fetchone()
        return (row["home_score"], row["away_score"]) if row else None


def update_score(match_id: str, home: int, away: int):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO match_scores(match_id,home_score,away_score) VALUES(?,?,?)",
            (match_id, home, away),
        )


def already_sent_today(send_type: str) -> bool:
    today = date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_sent WHERE send_date=? AND send_type=?",
            (today, send_type),
        ).fetchone()
        return row is not None


def mark_sent_today(send_type: str):
    today = date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_sent(send_date,send_type) VALUES(?,?)",
            (today, send_type),
        )


# ── Posts pendientes de publicar en X (botón "Publicar" de Telegram) ──────────

def add_pending_post(text: str, image_path: str | None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO pending_posts(text,image_path) VALUES(?,?)",
            (text, image_path),
        )
        return cur.lastrowid


def get_pending_post(post_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id,text,image_path,status FROM pending_posts WHERE id=?",
            (post_id,),
        ).fetchone()
        return dict(row) if row else None


def set_pending_status(post_id: int, status: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE pending_posts SET status=? WHERE id=?",
            (status, post_id),
        )


# ── Clave-valor genérico (offset de getUpdates de Telegram, etc.) ─────────────

def get_meta(key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key: str, value: str):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (key, value),
        )
