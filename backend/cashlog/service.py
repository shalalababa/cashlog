"""Application service layer used by the HTTP API.

Owns txn create/update/delete (with conversion + sync metadata), listing with
filters/sort/pagination, content autocomplete, rate lookup, and category/currency
management. Every mutation refreshes the JSON mirror. Money crosses this boundary
in *major* units (e.g. "5.51"); minor-unit integers stay inside the DB.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import date as _date
from typing import Any, Optional

from . import jsonsync, money, rates


def _validate_iso_date(value: Any) -> str:
    """Guard against non-ISO dates reaching the DB (the base-currency path skips
    the rate lookup that would otherwise reject them)."""
    try:
        return _date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise ValueError(f"invalid date (expected YYYY-MM-DD): {value!r}")


def _validate_direction(value: Any) -> str:
    if value not in ("expense", "income"):
        raise ValueError(f"invalid direction: {value!r}")
    return value


def _looks_like_aa(content: str) -> bool:
    return "AA" in (content or "").upper()


# ---------------------------------------------------------------------------
# Serialization (DB row -> API dict, minor -> major)
# ---------------------------------------------------------------------------
def serialize_txn(row: sqlite3.Row) -> dict:
    """``amount`` / ``base_cny`` are always the full stored amount (what the edit
    form round-trips). For a structured AA expense — settled or not —
    ``my_amount`` / ``my_base_cny`` carry my own share (txn_eff view), which is
    what the ledger displays and stats count; they are None for every other txn."""
    minor_unit = row["minor_unit"]
    base_cny = (money.base_micro_to_cny(row["base_amount_micro"])
                if row["base_amount_micro"] is not None else None)
    my_minor, my_base = row["my_minor"], row["my_base_micro"]
    return {
        "id": row["id"],
        "external_uid": row["external_uid"],
        "date": row["txn_date"],
        "direction": row["direction"],
        "amount": str(money.from_minor(row["amount_minor"], minor_unit)),
        "currency": row["code"],
        "currency_name": row["ccy_name"],
        "content": row["content"],
        "category_id": row["category_id"],
        "category": row["cat_name"],
        "category_color": row["cat_color"],
        "note": row["note"],
        "is_aa": bool(row["is_aa"]),
        "legacy_aa": (not bool(row["is_aa"])) and _looks_like_aa(row["content"]),
        "payer_id": row["payer_id"],
        "aa_settled": bool(row["aa_settled"]),
        "base_cny": str(base_cny) if base_cny is not None else None,
        "my_amount": (str(money.from_minor(my_minor, minor_unit))
                      if my_minor is not None else None),
        "my_base_cny": str(money.base_micro_to_cny(my_base)) if my_base is not None else None,
        "rate_used": row["rate_used"],
        "rate_date_used": row["rate_date_used"],
        "rate_stale_days": row["rate_stale_days"],
        "rate_stale": rates.is_stale(row["rate_stale_days"]),
        "has_rate": row["base_amount_micro"] is not None,
        "revision": row["revision"],
    }


_TXN_SELECT = """
    SELECT t.*, cur.code AS code, cur.name AS ccy_name, cur.minor_unit,
           c.name AS cat_name, c.color AS cat_color
    FROM   txn_eff t
    JOIN   currency cur ON cur.id = t.currency_id
    LEFT   JOIN category c ON c.id = t.category_id
"""

_SORT_COLUMNS = {
    # amount / base_cny sort by what the ledger displays (my share for AA).
    "date": "t.txn_date", "amount": "COALESCE(t.my_minor, t.amount_minor)", "content": "t.content",
    "category": "c.name", "currency": "cur.code",
    "base_cny": "COALESCE(t.my_base_micro, t.base_amount_micro)",
}


def get_txn(conn: sqlite3.Connection, txn_id: int) -> Optional[dict]:
    row = conn.execute(_TXN_SELECT + " WHERE t.id = ?", (txn_id,)).fetchone()
    return serialize_txn(row) if row else None


def list_txns(conn: sqlite3.Connection, *, direction: Optional[str] = None,
              search: Optional[str] = None, category_id: Optional[int] = None,
              currency: Optional[str] = None, date_from: Optional[str] = None,
              date_to: Optional[str] = None, aa: Optional[str] = None,
              uncategorized: bool = False, sort: str = "date", order: str = "desc",
              limit: int = 100, offset: int = 0) -> dict:
    where: list = []
    params: list = []
    if direction in ("expense", "income"):
        where.append("t.direction = ?"); params.append(direction)
    if search:
        where.append("t.content LIKE ? ESCAPE '\\'")
        params.append("%" + _escape_like(search) + "%")
    if category_id is not None:
        where.append("t.category_id = ?"); params.append(category_id)
    if uncategorized:
        where.append("t.category_id IS NULL")
    if currency:
        where.append("cur.code = ?"); params.append(currency)
    if date_from:
        where.append("t.txn_date >= ?"); params.append(date_from)
    if date_to:
        where.append("t.txn_date <= ?"); params.append(date_to)
    if aa == "aa":
        where.append("(t.is_aa = 1 OR UPPER(t.content) LIKE '%AA%')")
    elif aa == "unsettled":
        where.append("t.is_aa = 1 AND t.aa_settled = 0")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM txn t JOIN currency cur ON cur.id = t.currency_id"
        " LEFT JOIN category c ON c.id = t.category_id" + where_sql, params
    ).fetchone()["n"]

    sort_col = _SORT_COLUMNS.get(sort, "t.txn_date")
    direction_sql = "ASC" if str(order).lower() == "asc" else "DESC"
    rows = conn.execute(
        _TXN_SELECT + where_sql + f" ORDER BY {sort_col} {direction_sql}, t.id {direction_sql}"
        " LIMIT ? OFFSET ?", params + [limit, offset]
    ).fetchall()
    return {"items": [serialize_txn(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def _conversion(conn, currency_id: int, minor_unit: int, txn_date: str, amount_minor: int):
    base_id = rates.get_base_currency_id(conn)
    rl = rates.lookup(conn, currency_id, txn_date, base_currency_id=base_id)
    if rl is None:
        return None, None, 0, None
    base_micro = money.to_base_micro(amount_minor, minor_unit, rl.rate_to_base)
    return rl.rate_to_base, rl.rate_date, rl.stale_days, base_micro


def _currency(conn, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, minor_unit FROM currency WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValueError(f"unknown currency: {code}")
    return row


def create_txn(conn: sqlite3.Connection, data: dict, *, write_json: bool = True) -> dict:
    txn_date = _validate_iso_date(data["date"])
    direction = _validate_direction(data["direction"])
    cur = _currency(conn, data["currency"])
    amount_minor = money.to_minor(data["amount"], cur["minor_unit"])
    rate_used, rate_date, stale, base_micro = _conversion(
        conn, cur["id"], cur["minor_unit"], txn_date, amount_minor)
    uid = uuid.uuid4().hex
    try:
        cursor = conn.execute(
            """INSERT INTO txn (external_uid, txn_date, direction, amount_minor,
                   currency_id, content, category_id, note, is_aa, payer_id, aa_settled,
                   rate_used, rate_date_used, base_amount_micro, rate_stale_days,
                   revision, source_sheet)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'app')""",
            (uid, txn_date, direction, amount_minor, cur["id"],
             data.get("content", ""), data.get("category_id"), data.get("note"),
             int(data.get("is_aa", 0)), data.get("payer_id"), int(data.get("aa_settled", 0)),
             rate_used, rate_date, base_micro, stale))
    except sqlite3.IntegrityError as exc:
        raise ValueError(str(exc)) from exc
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return get_txn(conn, cursor.lastrowid)


def update_txn(conn: sqlite3.Connection, txn_id: int, data: dict, *,
               write_json: bool = True) -> dict:
    existing = conn.execute("SELECT * FROM txn WHERE id = ?", (txn_id,)).fetchone()
    if existing is None:
        raise KeyError(txn_id)
    txn_date = _validate_iso_date(data["date"])
    direction = _validate_direction(data["direction"])
    cur = _currency(conn, data["currency"])
    amount_minor = money.to_minor(data["amount"], cur["minor_unit"])
    rate_used, rate_date, stale, base_micro = _conversion(
        conn, cur["id"], cur["minor_unit"], txn_date, amount_minor)
    try:
        conn.execute(
            """UPDATE txn SET txn_date=?, direction=?, amount_minor=?, currency_id=?,
                   content=?, category_id=?, note=?, is_aa=?, payer_id=?, aa_settled=?,
                   rate_used=?, rate_date_used=?, base_amount_micro=?, rate_stale_days=?,
                   revision = revision + 1
               WHERE id = ?""",
            (txn_date, direction, amount_minor, cur["id"],
             data.get("content", ""), data.get("category_id"), data.get("note"),
             int(data.get("is_aa", 0)), data.get("payer_id"), int(data.get("aa_settled", 0)),
             rate_used, rate_date, base_micro, stale, txn_id))
    except sqlite3.IntegrityError as exc:
        raise ValueError(str(exc)) from exc
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return get_txn(conn, txn_id)


def delete_txn(conn: sqlite3.Connection, txn_id: int, *, write_json: bool = True) -> bool:
    cur = conn.execute("DELETE FROM txn WHERE id = ?", (txn_id,))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Autocomplete + rate lookup
# ---------------------------------------------------------------------------
def autocomplete(conn: sqlite3.Connection, direction: str, prefix: str,
                 limit: int = 8) -> list:
    if not prefix:
        return []
    pattern = _escape_like(prefix) + "%"
    rows = conn.execute(
        """SELECT content, COUNT(*) AS freq, MAX(txn_date) AS last_used
           FROM   txn
           WHERE  direction = ? AND content LIKE ? ESCAPE '\\' AND content <> ''
           GROUP BY content
           ORDER BY freq DESC, last_used DESC
           LIMIT ?""",
        (direction, pattern, limit)).fetchall()
    return [{"content": r["content"], "freq": r["freq"], "last_used": r["last_used"],
             "category_id": _suggested_category(conn, direction, r["content"])}
            for r in rows]


def _suggested_category(conn: sqlite3.Connection, direction: str,
                        content: str) -> Optional[int]:
    """The category this content was most often filed under (ties -> most
    recent). Only active categories of the matching kind count, so picking a
    suggestion never selects something the form's dropdown can't show."""
    row = conn.execute(
        """SELECT t.category_id
           FROM   txn t JOIN category c ON c.id = t.category_id
           WHERE  t.direction = ? AND t.content = ?
             AND  c.active = 1 AND c.kind = t.direction
           GROUP BY t.category_id
           ORDER BY COUNT(*) DESC, MAX(t.txn_date) DESC, MAX(t.id) DESC
           LIMIT 1""",
        (direction, content)).fetchone()
    return row["category_id"] if row else None


def rate_for(conn: sqlite3.Connection, currency: str, on_date: str) -> dict:
    on_date = _validate_iso_date(on_date)
    cur = _currency(conn, currency)
    base_id = rates.get_base_currency_id(conn)
    rl = rates.lookup(conn, cur["id"], on_date, base_currency_id=base_id)
    if rl is None:
        return {"found": False, "currency": currency, "date": on_date}
    return {"found": True, "currency": currency, "date": on_date,
            "rate": rl.rate_to_base, "rate_date": rl.rate_date,
            "stale_days": rl.stale_days, "stale": rates.is_stale(rl.stale_days)}


# ---------------------------------------------------------------------------
# Reference data (dropdowns + management)
# ---------------------------------------------------------------------------
def list_currencies(conn: sqlite3.Connection) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name, symbol, minor_unit, is_base, active FROM currency ORDER BY is_base DESC, code")]


def list_categories(conn: sqlite3.Connection, kind: Optional[str] = None) -> list:
    q = "SELECT id, name, kind, color, icon, exclude_stats, sort_order, active FROM category"
    params: list = []
    if kind:
        q += " WHERE kind = ?"; params.append(kind)
    q += " ORDER BY kind, sort_order, name"
    return [dict(r) for r in conn.execute(q, params)]


def create_category(conn: sqlite3.Connection, data: dict) -> dict:
    cur = conn.execute(
        """INSERT INTO category (name, kind, color, icon, exclude_stats, sort_order)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (data["name"], data["kind"], data.get("color"), data.get("icon"),
         int(data.get("exclude_stats", 0)), int(data.get("sort_order", 0))))
    conn.commit()
    row = conn.execute("SELECT id, name, kind, color, icon, exclude_stats, sort_order, active"
                       " FROM category WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_category(conn: sqlite3.Connection, cat_id: int, data: dict) -> dict:
    fields = []
    params: list = []
    for key in ("name", "color", "icon", "exclude_stats", "sort_order", "active"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(int(data[key]) if key in ("exclude_stats", "sort_order", "active") else data[key])
    if fields:
        params.append(cat_id)
        conn.execute(f"UPDATE category SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
    row = conn.execute("SELECT id, name, kind, color, icon, exclude_stats, sort_order, active"
                       " FROM category WHERE id = ?", (cat_id,)).fetchone()
    if row is None:
        raise KeyError(cat_id)
    return dict(row)
