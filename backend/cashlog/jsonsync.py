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

from . import config

# Tables exported, in dependency order.
TABLES = [
    "currency", "exchange_rate", "category", "person",
    "txn", "txn_participant", "fiscal_month",
    "aa_session", "aa_session_item", "aa_session_item_share", "setting",
]


def export_json(conn: sqlite3.Connection, path: Optional[Path] = None) -> Path:
    out_path = Path(path) if path else config.JSON_MIRROR_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "_meta": {
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    for table in TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        payload[table] = [dict(row) for row in rows]

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path
