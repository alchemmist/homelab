"""Wallpaper rows in Postgres, with SQLite for local runs and tests."""

import os
import sqlite3
import uuid
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallpaper (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  filename TEXT NOT NULL,
  status TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  width INTEGER,
  height INTEGER,
  error TEXT
)
"""


class Database:
    def insert(self, wallpaper_id: str, filename: str) -> None:
        raise NotImplementedError

    def list_all(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get(self, wallpaper_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def set_status(self, wallpaper_id: str, status: str, width: int | None, height: int | None, error: str | None) -> None:
        raise NotImplementedError

    def set_active(self, wallpaper_id: str, active: bool) -> None:
        raise NotImplementedError

    def delete(self, wallpaper_id: str) -> None:
        raise NotImplementedError

    def set_execution(self, wallpaper_id: str, url: str) -> None:
        raise NotImplementedError

    def active_ready(self) -> list[str]:
        raise NotImplementedError


def _row(item: dict[str, Any]) -> dict[str, Any]:
    item["active"] = bool(item["active"])
    return item


class SQLiteDB(Database):
    def __init__(self, path: str) -> None:
        self.path = path
        with self._conn() as conn:
            conn.execute(SCHEMA)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(wallpaper)")]
            if "execution_url" not in cols:
                conn.execute("ALTER TABLE wallpaper ADD COLUMN execution_url TEXT")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert(self, wallpaper_id: str, filename: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO wallpaper (id, filename, status) VALUES (?, ?, 'uploaded')",
                (wallpaper_id, filename),
            )

    def list_all(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM wallpaper ORDER BY created_at DESC").fetchall()
        return [_row(dict(row)) for row in rows]

    def get(self, wallpaper_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM wallpaper WHERE id = ?", (wallpaper_id,)).fetchone()
        return _row(dict(row)) if row else None

    def set_status(self, wallpaper_id: str, status: str, width: int | None, height: int | None, error: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE wallpaper SET status=?, width=?, height=?, error=? WHERE id=?",
                (status, width, height, error, wallpaper_id),
            )

    def set_active(self, wallpaper_id: str, active: bool) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE wallpaper SET active=? WHERE id=?", (int(active), wallpaper_id))

    def delete(self, wallpaper_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM wallpaper WHERE id=?", (wallpaper_id,))

    def set_execution(self, wallpaper_id: str, url: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE wallpaper SET execution_url=? WHERE id=?", (url, wallpaper_id))

    def active_ready(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM wallpaper WHERE active=1 AND status='ready' ORDER BY id"
            ).fetchall()
        return [row["id"] for row in rows]


class PostgresDB(Database):
    def __init__(self, url: str) -> None:
        import psycopg

        self.url = url
        self.psycopg = psycopg
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wallpaper (
                  id TEXT PRIMARY KEY,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  filename TEXT NOT NULL,
                  status TEXT NOT NULL,
                  active BOOLEAN NOT NULL DEFAULT FALSE,
                  width INTEGER,
                  height INTEGER,
                  error TEXT,
                  execution_url TEXT
                )
                """
            )
            conn.execute("ALTER TABLE wallpaper ADD COLUMN IF NOT EXISTS execution_url TEXT")

    def _conn(self):
        return self.psycopg.connect(self.url, autocommit=True)

    def insert(self, wallpaper_id: str, filename: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO wallpaper (id, filename, status) VALUES (%s, %s, 'uploaded')",
                (wallpaper_id, filename),
            )

    def list_all(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM wallpaper ORDER BY created_at DESC").fetchall()
            cols = [d.name for d in conn.description or []] if False else None
        # description is consumed; select columns explicitly
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, created_at::text, filename, status, active, width, height, error, execution_url FROM wallpaper ORDER BY created_at DESC"
            )
            return [
                _row({"id": r[0], "created_at": r[1], "filename": r[2], "status": r[3], "active": r[4], "width": r[5], "height": r[6], "error": r[7], "execution_url": r[8]})
                for r in cur.fetchall()
            ]

    def get(self, wallpaper_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, created_at::text, filename, status, active, width, height, error, execution_url FROM wallpaper WHERE id=%s",
                (wallpaper_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _row({"id": row[0], "created_at": row[1], "filename": row[2], "status": row[3], "active": row[4], "width": row[5], "height": row[6], "error": row[7], "execution_url": row[8]})

    def set_status(self, wallpaper_id: str, status: str, width: int | None, height: int | None, error: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE wallpaper SET status=%s, width=%s, height=%s, error=%s WHERE id=%s",
                (status, width, height, error, wallpaper_id),
            )

    def set_active(self, wallpaper_id: str, active: bool) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE wallpaper SET active=%s WHERE id=%s", (active, wallpaper_id))

    def delete(self, wallpaper_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM wallpaper WHERE id=%s", (wallpaper_id,))

    def set_execution(self, wallpaper_id: str, url: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE wallpaper SET execution_url=%s WHERE id=%s", (url, wallpaper_id))

    def active_ready(self) -> list[str]:
        with self._conn() as conn:
            cur = conn.execute("SELECT id FROM wallpaper WHERE active AND status='ready' ORDER BY id")
            return [row[0] for row in cur.fetchall()]


def open_db() -> Database:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres"):
        return PostgresDB(url)
    return SQLiteDB(os.environ.get("WALLPAPER_SQLITE", "/tmp/authentik-wallpapers.sqlite"))


def new_id() -> str:
    return uuid.uuid4().hex
