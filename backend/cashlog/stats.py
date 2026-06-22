"""Statistics engine: fiscal-month totals + category breakdowns + trends.

The fiscal-month numbers replicate the workbook's 统计 sheet exactly. Its SUMIFS
formula sums 人民币换算 (our cached `base_amount_micro`) for expenses in the
half-open window ``[period_end - 1 month, period_end)``, excluding categories
flagged ``exclude_stats`` (学费 / 特殊). Uncategorized rows are *included* — the
spreadsheet only excludes the two named categories. USD conversion uses the rate
dated on-or-before the fiscal close (当日汇率), and the credit-card figure is the
manual ``fiscal_month`` value. Ratios may exceed 100% by design.

The breakdown / trend helpers serve the interactive charts. They return all
categories (with the ``exclude_stats`` flag) so the frontend can hide/restore
them without another round-trip; uncategorized is its own bucket. Money is summed
as integer micro-units and converted to CNY once, at the end.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from . import config, money, rates

_UNCATEGORIZED = "未分类"
_UNCAT_COLOR = "#9aa3b2"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _iso(d: date) -> str:
    return d.isoformat()


def _parse(value: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        raise ValueError(f"invalid date (expected YYYY-MM-DD): {value!r}")


def edate(d: date, months: int) -> date:
    """Excel EDATE: shift by whole months, clamping the day to month end."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    # Last valid day of the target month.
    if month == 12:
        last = 31
    else:
        last = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def fiscal_range(period_end: str) -> tuple[str, str]:
    """Half-open ``[start, period_end)`` window for a fiscal close (the 5th)."""
    end = _parse(period_end)
    return _iso(edate(end, -1)), _iso(end)


# ---------------------------------------------------------------------------
# Period bucketing (for trends)
# ---------------------------------------------------------------------------
def _period_key(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return f"{d.year:04d}-{d.month:02d}"          # month (default)


def _enumerate_periods(start: date, end: date, granularity: str) -> list[str]:
    """Ordered, gap-filled period keys covering [start, end] inclusive."""
    if start > end:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    cur = start
    while cur <= end:
        k = _period_key(cur, granularity)
        if k not in seen:
            seen.add(k)
            keys.append(k)
        cur += timedelta(days=1)
    return keys


def _micro_to_cny_float(micro: int) -> float:
    return float(money.base_micro_to_cny(micro))


def _validate_direction(direction: str) -> str:
    if direction not in ("expense", "income"):
        raise ValueError(f"invalid direction: {direction!r}")
    return direction


# ---------------------------------------------------------------------------
# Fiscal-month statistics (replicates 统计)
# ---------------------------------------------------------------------------
def fiscal_months(conn: sqlite3.Connection) -> list[dict]:
    base_id = rates.get_base_currency_id(conn)
    out: list[dict] = []
    for fm in conn.execute("SELECT * FROM fiscal_month ORDER BY period_end"):
        period_end = fm["period_end"]
        start, end_excl = fiscal_range(period_end)

        micro = conn.execute(
            """SELECT COALESCE(SUM(COALESCE(t.base_amount_micro, 0)), 0) AS m
               FROM   txn t
               LEFT   JOIN category c ON c.id = t.category_id
               WHERE  t.direction = 'expense'
                 AND  t.txn_date >= ? AND t.txn_date < ?
                 AND  COALESCE(c.exclude_stats, 0) = 0""",
            (start, end_excl)).fetchone()["m"]
        total_cny = money.base_micro_to_cny(micro)

        cc_id = fm["credit_card_ccy_id"]
        rl = rates.lookup(conn, cc_id, period_end, base_currency_id=base_id) if cc_id else None
        usd_rate = Decimal(rl.rate_to_base) if rl else None
        rate_stale = bool(rl and rates.is_stale(rl.stale_days))

        cc_minor = fm["credit_card_amount_minor"]
        cc_minor_unit = conn.execute(
            "SELECT minor_unit FROM currency WHERE id = ?", (cc_id,)).fetchone()
        cc_major = (money.from_minor(cc_minor, cc_minor_unit["minor_unit"])
                    if cc_minor_unit else Decimal(0))

        total_usd = (_q2(total_cny / usd_rate) if usd_rate and usd_rate != 0 else None)
        cc_cny = _q2(cc_major * usd_rate) if usd_rate is not None else None
        ratio = (float(cc_cny / total_cny) if cc_cny is not None and total_cny != 0 else None)

        out.append({
            "period_end": period_end,
            "range_start": start,
            "range_end": _iso(_parse(end_excl) - timedelta(days=1)),  # inclusive, for chart range calls
            "total_cny": float(total_cny),
            "total_usd": float(total_usd) if total_usd is not None else None,
            "credit_card": float(cc_major),
            "credit_card_currency": _ccy_code(conn, cc_id),
            "credit_card_cny": float(cc_cny) if cc_cny is not None else None,
            "usd_rate": float(usd_rate) if usd_rate is not None else None,
            "ratio": ratio,
            "rate_stale": rate_stale,
        })
    return out


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ccy_code(conn: sqlite3.Connection, ccy_id: Optional[int]) -> Optional[str]:
    if ccy_id is None:
        return None
    row = conn.execute("SELECT code FROM currency WHERE id = ?", (ccy_id,)).fetchone()
    return row["code"] if row else None


# ---------------------------------------------------------------------------
# Category breakdown (treemap / donut for one date range)
# ---------------------------------------------------------------------------
def category_breakdown(conn: sqlite3.Connection, date_from: str, date_to: str, *,
                       direction: str = "expense") -> list[dict]:
    """Per-category CNY totals over the inclusive range ``[date_from, date_to]``.

    Returns every category that has activity (uncategorized as its own bucket),
    signed totals included; the frontend filters/normalises for display.
    """
    _validate_direction(direction)
    df, dt = _iso(_parse(date_from)), _iso(_parse(date_to))
    rows = conn.execute(
        """SELECT t.category_id AS cid,
                  c.name        AS name,
                  c.color       AS color,
                  COALESCE(c.exclude_stats, 0) AS exclude_stats,
                  COALESCE(SUM(COALESCE(t.base_amount_micro, 0)), 0) AS micro,
                  COUNT(*) AS n
           FROM   txn t
           LEFT   JOIN category c ON c.id = t.category_id
           WHERE  t.direction = ? AND t.txn_date >= ? AND t.txn_date <= ?
           GROUP BY t.category_id
           ORDER BY micro DESC""",
        (direction, df, dt)).fetchall()
    out = []
    for r in rows:
        out.append({
            "category_id": r["cid"],
            "category": r["name"] if r["cid"] is not None else _UNCATEGORIZED,
            "color": (r["color"] or _UNCAT_COLOR) if r["cid"] is not None else _UNCAT_COLOR,
            "exclude_stats": bool(r["exclude_stats"]),
            "total": _micro_to_cny_float(r["micro"]),
            "count": r["n"],
        })
    return out


# ---------------------------------------------------------------------------
# Category trend (amount per category per period — drives trend + share charts)
# ---------------------------------------------------------------------------
def category_trend(conn: sqlite3.Connection, date_from: str, date_to: str, *,
                   granularity: str = "month", direction: str = "expense") -> dict:
    _validate_direction(direction)
    if granularity not in ("day", "week", "month"):
        raise ValueError(f"invalid granularity: {granularity!r}")
    start, end = _parse(date_from), _parse(date_to)
    periods = _enumerate_periods(start, end, granularity)
    idx = {k: i for i, k in enumerate(periods)}

    rows = conn.execute(
        """SELECT t.txn_date AS d, t.category_id AS cid,
                  c.name AS name, c.color AS color,
                  COALESCE(c.exclude_stats, 0) AS exclude_stats,
                  COALESCE(t.base_amount_micro, 0) AS micro
           FROM   txn t
           LEFT   JOIN category c ON c.id = t.category_id
           WHERE  t.direction = ? AND t.txn_date >= ? AND t.txn_date <= ?""",
        (direction, _iso(start), _iso(end))).fetchall()

    series: dict = {}    # cid -> {meta + micro list}
    order: list = []     # preserve first-seen category order
    for r in rows:
        cid = r["cid"]
        if cid not in series:
            series[cid] = {
                "category_id": cid,
                "category": r["name"] if cid is not None else _UNCATEGORIZED,
                "color": (r["color"] or _UNCAT_COLOR) if cid is not None else _UNCAT_COLOR,
                "exclude_stats": bool(r["exclude_stats"]),
                "_micro": [0] * len(periods),
            }
            order.append(cid)
        key = _period_key(_parse(r["d"]), granularity)
        pos = idx.get(key)
        if pos is not None:
            series[cid]["_micro"][pos] += r["micro"]

    out_series = []
    for cid in order:
        s = series[cid]
        out_series.append({
            "category_id": s["category_id"],
            "category": s["category"],
            "color": s["color"],
            "exclude_stats": s["exclude_stats"],
            "values": [_micro_to_cny_float(m) for m in s["_micro"]],
        })
    # Largest total first, so stacked charts read top-down by importance.
    out_series.sort(key=lambda s: sum(s["values"]), reverse=True)
    return {"periods": periods, "granularity": granularity, "series": out_series}
