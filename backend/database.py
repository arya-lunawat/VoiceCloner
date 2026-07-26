"""
Free local database layer using SQLite (no server, no cost).
Swap DB_PATH / connection logic for PostgreSQL later if you scale up -
the schema below maps directly onto a Postgres table if you do.
"""
import sqlite3
import os
import uuid
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "voice_clone.db"))


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                consent_confirmed INTEGER NOT NULL DEFAULT 0,
                source_files TEXT NOT NULL,          -- JSON list of processed sample paths
                embedding_path TEXT,                  -- path to saved speaker latents (.pt)
                recording_path TEXT,                  -- original browser recording, if any
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing', -- processing | ready | failed
                is_saved INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id TEXT PRIMARY KEY,
                voice_profile_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_saved INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (voice_profile_id) REFERENCES voice_profiles (id)
            )
        """)
        _ensure_column(conn, "voice_profiles", "recording_path", "TEXT")
        _ensure_column(conn, "voice_profiles", "is_saved", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "generations", "is_saved", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "generations", "name", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_saved ON voice_profiles(is_saved)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_status ON voice_profiles(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_generations_saved ON generations(is_saved)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_generations_voice_profile ON generations(voice_profile_id)")
        conn.commit()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> str:
    return datetime.utcnow().isoformat()
