"""JSON mirror of the SQLite source of truth.

Written after every committed change so the data is diff-friendly, git-able,
and trivially backed up. This is a one-way export (DB -> JSON) in P1; xlsx
round-tripping is P2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Tables exported, in dependency order.
TABLES = [
    "currency", "exchange_rate", "category", "person",
    "txn", "txn_participant", "fiscal_month", "budget",
    "aa_session", "aa_session_item", "aa_session_item_share", "setting",
]


def mirror_path_for(conn: sqlite3.Connection) -> Path:
    """JSON mirror path derived from the connection's own DB file, so a temp DB
    mirrors next to itself and never overwrites the real data/cashlog.json.

    Raises for an in-memory database (no file) rather than silently defaulting to
    the real mirror — callers using :memory: must pass an explicit path."""
    row = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchone()
    db_file = row[0] if row else ""
    if not db_file:
        raise ValueError(
            "cannot derive a JSON mirror path for an in-memory database; "
            "pass an explicit path to export_json()")
    return Path(db_file).with_suffix(".json")


def export_json(conn: sqlite3.Connection, path: Optional[Path] = None) -> Path:
    out_path = Path(path) if path else mirror_path_for(conn)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "_meta": {
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    existing = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in TABLES:
        # A table may be absent on a DB created before its migration ran; skip it
        # rather than fail the whole mirror.
        if table not in existing:
            continue
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        payload[table] = [dict(row) for row in rows]

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path
