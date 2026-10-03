"""Small DB compatibility layer for the public AI Studio account store.

SQLite remains the zero-config development fallback. Production can set DATABASE_URL
to a PostgreSQL connection string (Render Postgres/Supabase/etc.).
"""
import os
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

    def _normalize_url(url: str) -> str:
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://"):]
        return url

    @contextmanager
    def db():
        conn = psycopg.connect(_normalize_url(DATABASE_URL), row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    PLACEHOLDER = "%s"
    IS_POSTGRES = True
else:
    import sqlite3

    @contextmanager
    def db():
        path = os.environ.get(
            "AI_STUDIO_DB_PATH",
            os.path.join(os.environ.get("AI_STUDIO_DATA_DIR", "/tmp/ai-studio"), "users.db"),
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    PLACEHOLDER = "?"
    IS_POSTGRES = False
