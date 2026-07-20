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

DB_PATH = os.path.join(os.path.dirname(__file__), "voice_clone.db")


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                consent_confirmed INTEGER NOT NULL DEFAULT 0,
                source_files TEXT NOT NULL,          -- JSON list of processed sample paths
                embedding_path TEXT,                  -- path to saved speaker latents (.pt)
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing'  -- processing | ready | failed
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
                FOREIGN KEY (voice_profile_id) REFERENCES voice_profiles (id)
            )
        """)
        conn.commit()


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
