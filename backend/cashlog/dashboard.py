"""Home dashboard (P6): a single read-only aggregation for the landing page.

Combines, for the current fiscal month:
  - this-month vs last-month total (with delta),
  - the leading expense categories,
  - budget progress (overall + per-category), and
  - an AA-unsettled reminder.

Everything is derived from the existing stats / budgets / aa_service layers so
the numbers always agree with the rest of the app. Nothing here writes.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from . import aa_service, budgets, money, rates, stats

_TOP_N = 6


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _usd_currency_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT id FROM currency WHERE code = 'USD'").fetchone()
    return row["id"] if row else None


def _month_summary(conn: sqlite3.Connection, period_end: date,
                   usd_id: Optional[int], base_id: int, *,
                   rate_lookup_date: Optional[date] = None) -> dict:
    start = stats.edate(period_end, -1)
    s_iso, e_iso = start.isoformat(), period_end.isoformat()
    micro = stats.expense_total_micro(conn, s_iso, e_iso)
    total_cny = money.base_micro_to_cny(micro)
    lookup_iso = (rate_lookup_date or period_end).isoformat()
    rl = rates.lookup(conn, usd_id, lookup_iso, base_currency_id=base_id) if usd_id else None
    usd_rate = Decimal(rl.rate_to_base) if rl else None
    total_usd = _q2(total_cny / usd_rate) if usd_rate and usd_rate != 0 else None
    return {
        "period_end": e_iso,
        "range_start": s_iso,
        "range_end": (period_end - timedelta(days=1)).isoformat(),
        "total_micro": micro,
        "total_cny": float(total_cny),
        "total_usd": float(total_usd) if total_usd is not None else None,
        "usd_rate": float(usd_rate) if usd_rate is not None else None,
        "usd_rate_date": rl.rate_date if rl else None,
        "rate_lookup_date": lookup_iso,
        "rate_stale": bool(rl and rates.is_stale(rl.stale_days)),
    }


def _cumulative_series(conn: sqlite3.Connection, start: date, end: date) -> list[float]:
    """Cumulative fiscal expense totals for [start, end], gap-filled by day."""
    if end < start:
        return []
    rows = conn.execute(
        """SELECT t.txn_date AS d,
                  COALESCE(SUM(COALESCE(t.eff_base_micro, 0)), 0) AS micro
           FROM   txn_eff t
           LEFT   JOIN category c ON c.id = t.category_id
           WHERE  t.direction = 'expense'
             AND  t.txn_date >= ? AND t.txn_date <= ?
             AND  COALESCE(c.exclude_stats, 0) = 0
           GROUP BY t.txn_date""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    daily = {r["d"]: r["micro"] for r in rows}
    out: list[float] = []
    running = 0
    cur = start
    while cur <= end:
        running += daily.get(cur.isoformat(), 0)
        out.append(float(money.base_micro_to_cny(running)))
        cur += timedelta(days=1)
    return out


def _cumulative_compare(conn: sqlite3.Connection, cur_end: date, prev_end: date,
                        today: date) -> dict:
    cur_start = stats.edate(cur_end, -1)
    prev_start = stats.edate(prev_end, -1)
    cur_last = min(today, cur_end - timedelta(days=1))
    if cur_last < cur_start:
        cur_last = cur_start
    elapsed_days = (cur_last - cur_start).days + 1
    prev_last = min(prev_start + timedelta(days=elapsed_days - 1),
                    prev_end - timedelta(days=1))
    days = list(range(1, elapsed_days + 1))
    return {
        "days": days,
        "current": {
            "label": "本财政月",
            "range_start": cur_start.isoformat(),
            "range_end": cur_last.isoformat(),
            "values": _cumulative_series(conn, cur_start, cur_last),
        },
        "previous": {
            "label": "上财政月",
            "range_start": prev_start.isoformat(),
            "range_end": prev_last.isoformat(),
            "values": _cumulative_series(conn, prev_start, prev_last),
        },
    }


def _aa_summary(conn: sqlite3.Connection) -> dict:
    """Light count + per-currency total of unsettled AA (for the reminder card)."""
    groups = aa_service.list_unsettled(conn)
    by_currency = []
    total_count = 0
    for g in groups:
        count = len(g["txns"])
        total_count += count
        amount = sum((Decimal(t["amount"]) for t in g["txns"]), Decimal(0))
        by_currency.append({"currency": g["currency"], "count": count,
                            "amount": str(amount)})
    return {"count": total_count, "by_currency": by_currency}


def dashboard(conn: sqlite3.Connection, today: Optional[str] = None) -> dict:
    t = stats._parse(today) if today else date.today()
    cur_end = stats.current_fiscal_end(t)
    prev_end = stats.edate(cur_end, -1)
    base_id = rates.get_base_currency_id(conn)
    usd_id = _usd_currency_id(conn)

    current_lookup_date = min(t, cur_end)
    current = _month_summary(conn, cur_end, usd_id, base_id,
                             rate_lookup_date=current_lookup_date)
    previous = _month_summary(conn, prev_end, usd_id, base_id)

    delta_micro = current["total_micro"] - previous["total_micro"]
    current["delta"] = float(money.base_micro_to_cny(delta_micro))
    current["delta_pct"] = (delta_micro / previous["total_micro"]
                            if previous["total_micro"] else None)

    # Leading categories for the current month, following the fiscal rules
    # (drop exclude_stats, keep uncategorized), largest first.
    breakdown = stats.category_breakdown(conn, current["range_start"], current["range_end"])
    top = [c for c in breakdown if not c["exclude_stats"] and c["total"] > 0][:_TOP_N]

    return {
        "today": t.isoformat(),
        "current": current,
        "previous": previous,
        "top_categories": top,
        "cumulative": _cumulative_compare(conn, cur_end, prev_end, t),
        "budget": budgets.budget_status(conn, cur_end.isoformat()),
        "aa_unsettled": _aa_summary(conn),
    }
