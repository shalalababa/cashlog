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

from . import config, jsonsync, money, rates

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


def current_fiscal_end(today: date) -> date:
    """The ``period_end`` (a 5th) of the fiscal month ``today`` falls in.

    The window is half-open ``[period_end - 1 month, period_end)`` so a date on
    the 5th itself belongs to the *next* fiscal month. e.g. 2026-06-22 -> the
    2026-07-05 close; 2026-06-03 -> the 2026-06-05 close.
    """
    this_close = date(today.year, today.month, config.FISCAL_DAY)
    return this_close if today.day < config.FISCAL_DAY else edate(this_close, 1)


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
# Reusable expense aggregations over a half-open ``[start, end_excl)`` window.
# These mirror the 统计 SUMIFS so the dashboard / budgets stay consistent with
# the fiscal-month engine instead of re-deriving the rules.
# ---------------------------------------------------------------------------
def expense_total_micro(conn: sqlite3.Connection, start: str, end_excl: str, *,
                        exclude_flagged: bool = True) -> int:
    """Sum of the effective CNY (txn_eff.eff_base_micro) for expenses in ``[start, end_excl)``.

    With exclude_flagged (default) this is the headline fiscal total: it drops
    ``exclude_stats`` categories (学费 / 特殊) but keeps uncategorized rows.
    """
    flag = "AND COALESCE(c.exclude_stats, 0) = 0" if exclude_flagged else ""
    return conn.execute(
        f"""SELECT COALESCE(SUM(COALESCE(t.eff_base_micro, 0)), 0) AS m
            FROM   txn_eff t
            LEFT   JOIN category c ON c.id = t.category_id
            WHERE  t.direction = 'expense'
              AND  t.txn_date >= ? AND t.txn_date < ? {flag}""",
        (start, end_excl)).fetchone()["m"]


def category_total_micro(conn: sqlite3.Connection, category_id: int,
                         start: str, end_excl: str) -> int:
    """Sum of the effective CNY (txn_eff.eff_base_micro) for one category's expenses in ``[start, end_excl)``.

    Used by per-category budget progress; a budget tracks the category as the
    user defined it, so the exclude_stats flag is intentionally not applied here.
    """
    return conn.execute(
        """SELECT COALESCE(SUM(COALESCE(eff_base_micro, 0)), 0) AS m
           FROM   txn_eff
           WHERE  direction = 'expense' AND category_id = ?
             AND  txn_date >= ? AND txn_date < ?""",
        (category_id, start, end_excl)).fetchone()["m"]


def _currency_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, code, minor_unit FROM currency WHERE code = ?",
        (str(code).upper(),),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown currency code: {code!r}")
    return row


def _validate_period_end(period_end: str) -> str:
    d = _parse(period_end)
    if d.day != config.FISCAL_DAY:
        raise ValueError(f"fiscal period_end must be day {config.FISCAL_DAY}: {period_end!r}")
    return d.isoformat()


def _parse_nonnegative_amount(value, field: str):
    dec = money.parse_decimal(value)
    if dec is None:
        raise ValueError(f"cannot parse {field}: {value!r}")
    if dec < 0:
        raise ValueError(f"{field} must be non-negative")
    return dec


# ---------------------------------------------------------------------------
# Fiscal-month statistics (replicates 统计)
# ---------------------------------------------------------------------------
def _fiscal_periods(conn: sqlite3.Connection, stored: list[str], today: date) -> list[str]:
    """Every fiscal close from the first one with data up to the current one.

    ``fiscal_month`` rows only exist for months whose manual inputs were saved
    (or imported from the workbook), so new months would otherwise never show
    up. Start at the earlier of the first stored close and the close of the
    first transaction; end at the later of the current close (``today``) and the
    close of the latest transaction / stored row; fill every gap in between.
    """
    ends = [_parse(p) for p in stored]
    first_txn, last_txn = conn.execute("SELECT MIN(txn_date), MAX(txn_date) FROM txn").fetchone()
    if first_txn:
        ends += [current_fiscal_end(_parse(first_txn)), current_fiscal_end(_parse(last_txn))]
    if not ends:
        return []
    ends.append(current_fiscal_end(today))
    cur, last = min(ends), max(ends)
    out: list[str] = []
    while cur <= last:
        out.append(_iso(cur))
        cur = edate(cur, 1)
    return out


def fiscal_months(conn: sqlite3.Connection, today: Optional[date] = None) -> list[dict]:
    """One row per fiscal month (see _fiscal_periods). Months without a stored
    ``fiscal_month`` row are shown with a zero USD credit-card figure; saving
    one (save_fiscal_month) upserts it. Read-only."""
    base_id = rates.get_base_currency_id(conn)
    stored = {r["period_end"]: r for r in conn.execute(
        """SELECT fm.*, o.total_override_micro
           FROM fiscal_month fm
           LEFT JOIN fiscal_month_total_override o ON o.period_end = fm.period_end""")}
    usd = conn.execute("SELECT id FROM currency WHERE code = 'USD'").fetchone()
    usd_id = usd["id"] if usd else None
    blank = {"credit_card_amount_minor": 0, "credit_card_ccy_id": usd_id,
             "total_override_micro": None}
    out: list[dict] = []
    for period_end in _fiscal_periods(conn, list(stored), today or date.today()):
        fm = stored.get(period_end, blank)
        start, end_excl = fiscal_range(period_end)

        computed_micro = expense_total_micro(conn, start, end_excl)
        override_micro = fm["total_override_micro"]
        effective_micro = override_micro if override_micro is not None else computed_micro
        computed_total_cny = money.base_micro_to_cny(computed_micro)
        total_cny = money.base_micro_to_cny(effective_micro)
        override_total_cny = (money.base_micro_to_cny(override_micro)
                              if override_micro is not None else None)

        # 美元换算 / 当日汇率 are always USD figures; the credit card may be in
        # another currency, so it is converted with its own rate.
        rl = rates.lookup(conn, usd_id, period_end, base_currency_id=base_id) if usd_id else None
        usd_rate = Decimal(rl.rate_to_base) if rl else None
        rate_stale = bool(rl and rates.is_stale(rl.stale_days))
        cc_id = fm["credit_card_ccy_id"]
        if cc_id == usd_id:
            cc_rate = usd_rate
        else:
            cc_rl = rates.lookup(conn, cc_id, period_end, base_currency_id=base_id) if cc_id else None
            cc_rate = Decimal(cc_rl.rate_to_base) if cc_rl else None

        cc_minor = fm["credit_card_amount_minor"]
        cc_minor_unit = conn.execute(
            "SELECT minor_unit FROM currency WHERE id = ?", (cc_id,)).fetchone()
        cc_major = (money.from_minor(cc_minor, cc_minor_unit["minor_unit"])
                    if cc_minor_unit else Decimal(0))

        total_usd = (_q2(total_cny / usd_rate) if usd_rate and usd_rate != 0 else None)
        cc_cny = _q2(cc_major * cc_rate) if cc_rate is not None else None
        ratio = (float(cc_cny / total_cny) if cc_cny is not None and total_cny != 0 else None)

        out.append({
            "period_end": period_end,
            "range_start": start,
            "range_end": _iso(_parse(end_excl) - timedelta(days=1)),  # inclusive, for chart range calls
            "total_cny": float(total_cny),
            "computed_total_cny": float(computed_total_cny),
            "total_cny_override": float(override_total_cny) if override_total_cny is not None else None,
            "total_cny_overridden": override_micro is not None,
            "total_usd": float(total_usd) if total_usd is not None else None,
            "credit_card": float(cc_major),
            "credit_card_currency": _ccy_code(conn, cc_id),
            "credit_card_cny": float(cc_cny) if cc_cny is not None else None,
            "usd_rate": float(usd_rate) if usd_rate is not None else None,
            "ratio": ratio,
            "rate_stale": rate_stale,
        })
    return out


def fiscal_headline_micro(conn: sqlite3.Connection, period_end: str) -> int:
    """The fiscal month's headline total as the stats page shows it: the manual
    override when one is set, else the computed SUMIFS total."""
    row = conn.execute("SELECT total_override_micro FROM fiscal_month_total_override "
                       "WHERE period_end = ?", (period_end,)).fetchone()
    if row is not None and row["total_override_micro"] is not None:
        return row["total_override_micro"]
    start, end_excl = fiscal_range(period_end)
    return expense_total_micro(conn, start, end_excl)


def fiscal_month(conn: sqlite3.Connection, period_end: str) -> dict:
    pe = _validate_period_end(period_end)
    for row in fiscal_months(conn):
        if row["period_end"] == pe:
            return row
    raise KeyError(pe)


def save_fiscal_month(conn: sqlite3.Connection, period_end: str, *, credit_card,
                      total_cny=None, credit_card_currency: str = "USD",
                      write_json: bool = True) -> dict:
    """Create/update one fiscal month's manual inputs.

    ``total_cny`` is optional. Blank/None clears the manual override and the
    headline total goes back to transaction-derived calculation.
    """
    pe = _validate_period_end(period_end)
    ccy = _currency_by_code(conn, credit_card_currency)
    cc_amount = _parse_nonnegative_amount(credit_card, "credit_card")
    cc_minor = money.to_minor(cc_amount, ccy["minor_unit"])

    conn.execute(
        """INSERT INTO fiscal_month (period_end, credit_card_amount_minor, credit_card_ccy_id)
           VALUES (?, ?, ?)
           ON CONFLICT(period_end) DO UPDATE SET
               credit_card_amount_minor = excluded.credit_card_amount_minor,
               credit_card_ccy_id = excluded.credit_card_ccy_id,
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        (pe, cc_minor, ccy["id"]),
    )

    if total_cny is None or str(total_cny).strip() == "":
        conn.execute("DELETE FROM fiscal_month_total_override WHERE period_end = ?", (pe,))
    else:
        total_micro = money.cny_to_base_micro(total_cny)
        conn.execute(
            """INSERT INTO fiscal_month_total_override (period_end, total_override_micro)
               VALUES (?, ?)
               ON CONFLICT(period_end) DO UPDATE SET
                   total_override_micro = excluded.total_override_micro,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (pe, total_micro),
        )

    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return fiscal_month(conn, pe)


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
                  COALESCE(SUM(COALESCE(t.eff_base_micro, 0)), 0) AS micro,
                  COUNT(*) AS n
           FROM   txn_eff t
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
                  COALESCE(t.eff_base_micro, 0) AS micro
           FROM   txn_eff t
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
