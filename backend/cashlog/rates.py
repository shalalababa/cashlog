"""Exchange-rate engine.

Replicates the workbook's INDEX/MATCH/MAX array formula: for a given currency
and date, use the most recent rate dated on-or-before that date. The base
currency (CNY) is always 1. Staleness = days between the txn date and the rate
date actually used, surfaced so the UI/report can flag long gaps.
"""
from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import config, money

FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"


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


def rate_status(conn: sqlite3.Connection) -> dict:
    """Summary used by the UI before/after a manual rate refresh."""
    currencies = []
    total_stale = 0
    total_missing = 0
    for c in conn.execute(
        """SELECT id, code, name, active
           FROM currency
           WHERE is_base = 0
           ORDER BY active DESC, code"""
    ):
        last_rate = conn.execute(
            "SELECT MAX(rate_date) AS d FROM exchange_rate WHERE currency_id = ?",
            (c["id"],),
        ).fetchone()["d"]
        counts = conn.execute(
            """SELECT COUNT(*) AS txn_count,
                      SUM(CASE WHEN base_amount_micro IS NULL THEN 1 ELSE 0 END) AS missing_count,
                      SUM(CASE WHEN rate_stale_days > ? THEN 1 ELSE 0 END) AS stale_count
               FROM txn
               WHERE currency_id = ?""",
            (config.STALE_RATE_DAYS, c["id"]),
        ).fetchone()
        stale_count = counts["stale_count"] or 0
        missing_count = counts["missing_count"] or 0
        total_stale += stale_count
        total_missing += missing_count
        currencies.append({
            "code": c["code"],
            "name": c["name"],
            "active": bool(c["active"]),
            "last_rate_date": last_rate,
            "txn_count": counts["txn_count"],
            "stale_txn_count": stale_count,
            "missing_txn_count": missing_count,
        })
    return {
        "stale_days": config.STALE_RATE_DAYS,
        "stale_txn_count": total_stale,
        "missing_txn_count": total_missing,
        "currencies": currencies,
    }


def fetch_frankfurter(base: str, quote: str, start: str, end: str) -> list[dict]:
    """Fetch a currency->base time series from Frankfurter v2.

    The public API returns an array of rows. We still validate every row before
    persisting it because third-party JSON is an untrusted boundary.
    """
    params = urlencode({"base": base, "quotes": quote, "from": start, "to": end})
    req = Request(
        f"{FRANKFURTER_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": "Cashlog/0.1"},
    )
    with urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return _validate_frankfurter_rows(payload, base, quote)


def _validate_frankfurter_rows(payload, base: str, quote: str) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("unexpected Frankfurter response: expected a list")
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("unexpected Frankfurter response row")
        if item.get("base") != base or item.get("quote") != quote:
            raise ValueError("Frankfurter response currency pair mismatch")
        rate_date = _parse_iso(str(item.get("date"))).isoformat()
        rate = money.parse_decimal(item.get("rate"))
        if rate is None or rate <= 0:
            raise ValueError("Frankfurter response has an invalid rate")
        rows.append({"date": rate_date, "rate": money.rate_to_str(rate)})
    return rows


def _codes_filter(conn: sqlite3.Connection, codes: Optional[Iterable[str]]) -> tuple[list[str], list[sqlite3.Row]]:
    params: list = []
    q = "SELECT id, code, minor_unit FROM currency WHERE is_base = 0"
    if codes:
        wanted = sorted({str(c).upper() for c in codes if str(c).strip()})
        q += f" AND code IN ({','.join('?' * len(wanted))})"
        params.extend(wanted)
    q += " ORDER BY code"
    rows = conn.execute(q, params).fetchall()
    if codes:
        found = {r["code"] for r in rows}
        missing = sorted(set(params) - found)
        if missing:
            raise ValueError(f"unknown currency code(s): {missing}")
    return params, rows


def _default_refresh_start(conn: sqlite3.Connection, currency_id: int) -> Optional[str]:
    """Pick the earliest date worth fetching for a currency.

    Prefer the first stale/missing transaction date. If everything is fresh,
    continue from the day after the latest stored rate. If the currency has no
    rates yet, start at its first transaction date.
    """
    stale = conn.execute(
        """SELECT MIN(txn_date) AS d
           FROM txn
           WHERE currency_id = ?
             AND (base_amount_micro IS NULL OR rate_stale_days > ?)""",
        (currency_id, config.STALE_RATE_DAYS),
    ).fetchone()["d"]
    if stale:
        return stale
    last = conn.execute(
        "SELECT MAX(rate_date) AS d FROM exchange_rate WHERE currency_id = ?",
        (currency_id,),
    ).fetchone()["d"]
    if last:
        return (_parse_iso(last) + timedelta(days=1)).isoformat()
    return conn.execute(
        "SELECT MIN(txn_date) AS d FROM txn WHERE currency_id = ?",
        (currency_id,),
    ).fetchone()["d"]


def recompute_txn_conversions(
    conn: sqlite3.Connection,
    *,
    currency_ids: Optional[Iterable[int]] = None,
) -> int:
    """Refresh cached CNY conversions after exchange_rate changes."""
    params: list = []
    q = ("SELECT t.id, t.currency_id, t.txn_date, t.amount_minor, cur.minor_unit "
         "FROM txn t JOIN currency cur ON cur.id = t.currency_id")
    ids = list(currency_ids or [])
    if ids:
        q += f" WHERE t.currency_id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    base_id = get_base_currency_id(conn)
    count = 0
    for t in conn.execute(q, params).fetchall():
        rl = lookup(conn, t["currency_id"], t["txn_date"], base_currency_id=base_id)
        if rl is None:
            values = (None, None, None, 0, t["id"])
        else:
            base_micro = money.to_base_micro(
                t["amount_minor"], t["minor_unit"], rl.rate_to_base)
            values = (rl.rate_to_base, rl.rate_date, base_micro, rl.stale_days, t["id"])
        conn.execute(
            """UPDATE txn
               SET rate_used = ?, rate_date_used = ?, base_amount_micro = ?,
                   rate_stale_days = ?
               WHERE id = ?""",
            values,
        )
        count += 1
    return count


def refresh_rates(
    conn: sqlite3.Connection,
    *,
    currency_codes: Optional[Iterable[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fetcher: Optional[Callable[[str, str, str, str], list[dict]]] = None,
    write_json: bool = True,
) -> dict:
    """Fetch rates for selected non-base currencies and recompute txn caches."""
    base = conn.execute("SELECT id, code FROM currency WHERE is_base = 1").fetchone()
    if base is None:
        raise RuntimeError("no base currency configured")

    end = _parse_iso(end_date).isoformat() if end_date else date.today().isoformat()
    explicit_start = _parse_iso(start_date).isoformat() if start_date else None
    fetch = fetcher or fetch_frankfurter
    _, currencies = _codes_filter(conn, currency_codes)

    per_currency = []
    touched_ids: list[int] = []
    inserted = updated = unchanged = fetched_total = 0

    for c in currencies:
        start = explicit_start or _default_refresh_start(conn, c["id"])
        if not start or start > end:
            per_currency.append({
                "code": c["code"], "start": start, "end": end,
                "fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0,
            })
            continue

        rows = fetch(c["code"], base["code"], start, end)
        ci = cu = cn = 0
        for row in rows:
            rate_date = _parse_iso(str(row["date"])).isoformat()
            if rate_date < start or rate_date > end:
                continue
            rate_dec = money.parse_decimal(row["rate"])
            if rate_dec is None or rate_dec <= 0:
                raise ValueError("fetched rate must be positive")
            rate = money.rate_to_str(rate_dec)
            existing = conn.execute(
                "SELECT rate_to_base FROM exchange_rate WHERE currency_id = ? AND rate_date = ?",
                (c["id"], rate_date),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base, source)
                       VALUES (?, ?, ?, 'frankfurter')""",
                    (c["id"], rate_date, rate),
                )
                ci += 1
            elif existing["rate_to_base"] != rate:
                conn.execute(
                    """UPDATE exchange_rate
                       SET rate_to_base = ?, source = 'frankfurter'
                       WHERE currency_id = ? AND rate_date = ?""",
                    (rate, c["id"], rate_date),
                )
                cu += 1
            else:
                cn += 1
        if rows:
            touched_ids.append(c["id"])
        inserted += ci
        updated += cu
        unchanged += cn
        fetched_total += len(rows)
        per_currency.append({
            "code": c["code"], "start": start, "end": end,
            "fetched": len(rows), "inserted": ci, "updated": cu, "unchanged": cn,
        })

    recomputed = recompute_txn_conversions(conn, currency_ids=touched_ids) if touched_ids else 0
    conn.commit()
    if write_json:
        from . import jsonsync
        jsonsync.export_json(conn)
    return {
        "provider": "frankfurter",
        "quote": base["code"],
        "end": end,
        "fetched": fetched_total,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "recomputed_txns": recomputed,
        "currencies": per_currency,
        "status": rate_status(conn),
    }
