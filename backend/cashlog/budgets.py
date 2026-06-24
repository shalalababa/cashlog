"""Budgets (P6): an overall per-fiscal-month spending target plus optional
per-category targets, each absolute (CNY) or a percentage of the overall.

Budgets are a planning overlay only. They are read by the dashboard / budget
views and never feed back into the fiscal-month statistics — the 统计 numbers
stay exactly as the workbook computed them (acceptance: 预算不影响历史统计口径).

Progress is evaluated against a fiscal month (default: the current one), using
the same ``[period_end - 1 month, period_end)`` window and the same SUMIFS rules
as ``stats``. Money crosses this boundary in *major* CNY units.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from . import jsonsync, money, stats

_ABSOLUTE = "absolute"
_PERCENT = "percent"
_HUNDRED = Decimal(100)


# ---------------------------------------------------------------------------
# Parsing / serialisation
# ---------------------------------------------------------------------------
def _parse_percent(raw) -> str:
    if raw in (None, ""):
        raise ValueError("percent budget requires a percent value")
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid percent: {raw!r}") from exc
    if d < 0:
        raise ValueError("percent must be >= 0")
    return str(d)


def _serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "category_id": row["category_id"],
        "amount_type": row["amount_type"],
        "amount": str(money.base_micro_to_cny(row["amount_micro"]))
        if row["amount_micro"] is not None else None,
        "amount_micro": row["amount_micro"],
        "percent": row["percent"],
        "note": row["note"],
    }


def _overall_micro(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT amount_micro FROM budget WHERE category_id IS NULL").fetchone()
    return row["amount_micro"] if row else None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def list_budgets(conn: sqlite3.Connection) -> dict:
    """Return ``{overall, categories}``; categories carry their name/color."""
    cats = {c["id"]: c for c in conn.execute(
        "SELECT id, name, color FROM category WHERE kind = 'expense'")}
    overall = None
    categories: list[dict] = []
    for row in conn.execute(
            "SELECT * FROM budget ORDER BY category_id IS NOT NULL, category_id"):
        b = _serialize(row)
        if row["category_id"] is None:
            overall = b
        else:
            c = cats.get(row["category_id"])
            b["category"] = c["name"] if c else None
            b["color"] = c["color"] if c else None
            categories.append(b)
    return {"overall": overall, "categories": categories}


# ---------------------------------------------------------------------------
# Write (single upsert keyed on category_id; NULL = the overall budget)
# ---------------------------------------------------------------------------
def set_budget(conn: sqlite3.Connection, *, category_id: Optional[int],
               amount_type: str = _ABSOLUTE, amount=None, percent=None,
               note: Optional[str] = None, write_json: bool = True) -> dict:
    if amount_type not in (_ABSOLUTE, _PERCENT):
        raise ValueError(f"invalid amount_type: {amount_type!r}")
    if category_id is None and amount_type != _ABSOLUTE:
        raise ValueError("the overall budget must be absolute")
    if category_id is not None:
        if not conn.execute("SELECT 1 FROM category WHERE id = ? AND kind = 'expense'",
                            (category_id,)).fetchone():
            raise ValueError(f"unknown expense category: {category_id}")

    amount_micro: Optional[int] = None
    pct: Optional[str] = None
    if amount_type == _ABSOLUTE:
        if amount in (None, ""):
            raise ValueError("absolute budget requires an amount")
        amount_micro = money.cny_to_base_micro(amount)
        if amount_micro < 0:
            raise ValueError("budget amount must be >= 0")
    else:
        pct = _parse_percent(percent)

    if category_id is None:
        existing = conn.execute(
            "SELECT id FROM budget WHERE category_id IS NULL").fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM budget WHERE category_id = ?", (category_id,)).fetchone()

    if existing:
        conn.execute(
            "UPDATE budget SET amount_type = ?, amount_micro = ?, percent = ?, note = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (amount_type, amount_micro, pct, note, existing["id"]))
        bid = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO budget (category_id, amount_type, amount_micro, percent, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (category_id, amount_type, amount_micro, pct, note))
        bid = cur.lastrowid
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return _serialize(conn.execute("SELECT * FROM budget WHERE id = ?", (bid,)).fetchone())


def delete_budget(conn: sqlite3.Connection, budget_id: int, *,
                  write_json: bool = True) -> bool:
    cur = conn.execute("DELETE FROM budget WHERE id = ?", (budget_id,))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Progress against a fiscal month
# ---------------------------------------------------------------------------
def _progress(limit_micro: Optional[int], actual_micro: int) -> dict:
    """Compare actual spend to a (possibly unresolved) limit, in CNY."""
    actual_cny = money.base_micro_to_cny(actual_micro)
    if limit_micro is None:
        return {"limit": None, "limit_micro": None,
                "actual": str(actual_cny), "actual_micro": actual_micro,
                "pct": None, "remaining": None, "over": False}
    remaining_micro = limit_micro - actual_micro
    pct = (actual_micro / limit_micro) if limit_micro > 0 else None
    return {
        "limit": str(money.base_micro_to_cny(limit_micro)),
        "limit_micro": limit_micro,
        "actual": str(actual_cny), "actual_micro": actual_micro,
        "pct": pct,
        "remaining": str(money.base_micro_to_cny(remaining_micro)),
        "over": actual_micro > limit_micro,
    }


def _resolve_limit_micro(row: dict, overall_micro: Optional[int]) -> Optional[int]:
    """Absolute -> its amount; percent -> that share of the overall budget
    (None if no overall budget is set, so the UI can flag it)."""
    if row["amount_type"] == _ABSOLUTE:
        return row["amount_micro"]
    if overall_micro is None:
        return None
    share = (Decimal(overall_micro) * Decimal(row["percent"]) / _HUNDRED).quantize(
        Decimal(1), rounding=ROUND_HALF_UP)
    return int(share)


def budget_status(conn: sqlite3.Connection, period_end: Optional[str] = None) -> dict:
    """Overall + per-category budget progress for a fiscal month (default: current)."""
    end = stats._parse(period_end) if period_end else stats.current_fiscal_end(date.today())
    start = stats.edate(end, -1)
    s_iso, e_iso = start.isoformat(), end.isoformat()

    data = list_budgets(conn)
    overall_row = data["overall"]
    overall_micro = overall_row["amount_micro"] if overall_row else None
    actual_overall = stats.expense_total_micro(conn, s_iso, e_iso)  # excludes 学费/特殊

    cats = []
    for cb in data["categories"]:
        limit_micro = _resolve_limit_micro(cb, overall_micro)
        actual_micro = stats.category_total_micro(conn, cb["category_id"], s_iso, e_iso)
        cats.append({
            "category_id": cb["category_id"], "category": cb.get("category"),
            "color": cb.get("color"), "amount_type": cb["amount_type"],
            "percent": cb["percent"], "budget_id": cb["id"],
            **_progress(limit_micro, actual_micro),
        })

    return {
        "period_end": e_iso, "range_start": s_iso,
        "range_end": (end - timedelta(days=1)).isoformat(),
        "has_overall": overall_micro is not None,
        "overall": {"budget_id": overall_row["id"] if overall_row else None,
                    **_progress(overall_micro, actual_overall)},
        "categories": cats,
    }
