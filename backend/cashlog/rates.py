"""Exchange-rate engine.

Replicates the workbook's INDEX/MATCH/MAX array formula: for a given currency
and date, use the most recent rate dated on-or-before that date. The base
currency (CNY) is always 1. Staleness = days between the txn date and the rate
date actually used, surfaced so the UI/report can flag long gaps.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import config


@dataclass(frozen=True)
class RateLookup:
    rate_to_base: str       # decimal string
    rate_date: Optional[str]  # ISO date the rate is dated; None for base currency
    stale_days: int


def _parse_iso(d: str) -> date:
    return date.fromisoformat(d[:10])


def lookup(
    conn: sqlite3.Connection,
    currency_id: int,
    on_date: str,
    *,
    base_currency_id: Optional[int] = None,
) -> Optional[RateLookup]:
    """Most-recent rate on-or-before on_date. None if no rate exists yet."""
    if base_currency_id is None:
        base_currency_id = get_base_currency_id(conn)

    if currency_id == base_currency_id:
        return RateLookup(rate_to_base="1", rate_date=None, stale_days=0)

    row = conn.execute(
        """SELECT rate_to_base, rate_date
           FROM   exchange_rate
           WHERE  currency_id = ? AND rate_date <= ?
           ORDER BY rate_date DESC
           LIMIT 1""",
        (currency_id, on_date),
    ).fetchone()
    if row is None:
        return None

    stale = (_parse_iso(on_date) - _parse_iso(row["rate_date"])).days
    return RateLookup(
        rate_to_base=row["rate_to_base"],
        rate_date=row["rate_date"],
        stale_days=max(stale, 0),
    )


def get_base_currency_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM currency WHERE is_base = 1").fetchone()
    if row is None:
        raise RuntimeError("no base currency configured")
    return row["id"]


def is_stale(stale_days: int) -> bool:
    return stale_days > config.STALE_RATE_DAYS
