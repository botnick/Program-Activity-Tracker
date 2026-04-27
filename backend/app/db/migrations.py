"""SQLite schema migrations for the activity tracker.

A single :func:`apply_migrations` is exposed; it reads the sibling ``schema.sql``
and executes it inside the supplied connection. The DDL is written with
``CREATE ... IF NOT EXISTS`` so the call is idempotent and safe on every
backend startup.

This module also pins the connection-level pragmas the rest of the storage
layer assumes (WAL journaling, NORMAL synchronous, foreign keys on).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply the schema and pragma settings to ``conn``.

    Idempotent: every DDL statement uses ``IF NOT EXISTS`` and the pragmas
    are always-safe to re-issue.
    """
    # WAL gives concurrent reads while a writer holds the write lock; the
    # combination with ``synchronous=NORMAL`` is the canonical "fast but
    # crash-safe" tuning recommended by the SQLite docs for app workloads.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
