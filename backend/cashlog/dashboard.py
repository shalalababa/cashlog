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
from decimal import Decimal
from typing import Optional

from . import aa_service, budgets, money, stats

_TOP_N = 6


def _month_summary(conn: sqlite3.Connection, period_end: date) -> dict:
    start = stats.edate(period_end, -1)
    s_iso, e_iso = start.isoformat(), period_end.isoformat()
    micro = stats.expense_total_micro(conn, s_iso, e_iso)
    return {
        "period_end": e_iso,
        "range_start": s_iso,
        "range_end": (period_end - timedelta(days=1)).isoformat(),
        "total_micro": micro,
        "total_cny": float(money.base_micro_to_cny(micro)),
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

    current = _month_summary(conn, cur_end)
    previous = _month_summary(conn, prev_end)

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
        "budget": budgets.budget_status(conn, cur_end.isoformat()),
        "aa_unsettled": _aa_summary(conn),
    }
