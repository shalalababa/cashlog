"""SQLite connection + schema application.

The schema lives in docs/schema.sql (single source of DDL). init_db applies it
to a fresh database. Re-initialising drops and rebuilds (safe in P1: no UID has
been written back to the workbook yet).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from . import config


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may run an endpoint and its dependency
    # cleanup on different threadpool threads. Each request still gets its own
    # connection (never shared concurrently), so this is safe.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None, *, reset: bool = False) -> Path:
    """Create the database from docs/schema.sql.

    With reset=True the existing file is removed first.
    """
    config.ensure_data_dirs()
    path = Path(db_path) if db_path else config.DB_PATH
    if reset:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()

    schema_sql = config.SCHEMA_SQL.read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path
