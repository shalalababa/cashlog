"""Seed reference data: currencies, categories, default self person.

Categories mirror the workbook's observed values. 学费 and 特殊 carry
exclude_stats=1 (excluded from fiscal-month totals). The importer also
creates any not-yet-seen category on the fly, so this is a convenience baseline
with stable colours/ordering, not an exhaustive list.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

# code, name, symbol, minor_unit, is_base
CURRENCIES = [
    ("CNY", "人民币", "¥", 2, 1),
    ("USD", "美元", "$", 2, 0),
    ("JPY", "日元", "¥", 0, 0),
    ("HKD", "港币", "HK$", 2, 0),
]

# name, exclude_stats, color  (kind = expense)
EXPENSE_CATEGORIES = [
    ("饮食", 0, "#FF6B6B"),
    ("交通", 0, "#4D96FF"),
    ("生活用品", 0, "#6BCB77"),
    ("学习用品", 0, "#FFD93D"),
    ("游戏", 0, "#9B5DE5"),
    ("网络", 0, "#00BBF9"),
    ("医疗", 0, "#F15BB5"),
    ("电子产品", 0, "#00C2A8"),
    ("学费", 1, "#8D99AE"),
    ("住宿", 0, "#FF9F1C"),
    ("信用卡利息", 0, "#E07A5F"),
    ("旅游", 0, "#3D9970"),
    ("娱乐", 0, "#F4A261"),
    ("贷款", 0, "#B5838D"),
    ("礼物", 0, "#FF8FA3"),
    ("特殊", 1, "#6C757D"),
    ("服装", 0, "#C77DFF"),
    ("服务费/小费", 0, "#A0C4FF"),
]

# name, color  (kind = income)
INCOME_CATEGORIES = [
    ("利息", "#2EC4B6"),
    ("跨境汇款", "#118AB2"),
    ("个人换汇", "#06D6A0"),
    ("退款", "#FFD166"),
    ("信用卡返现", "#EF476F"),
    ("奖学金", "#073B4C"),
    ("退税", "#7209B7"),
]


def seed(conn: sqlite3.Connection) -> None:
    for code, name, symbol, minor_unit, is_base in CURRENCIES:
        conn.execute(
            """INSERT INTO currency (code, name, symbol, minor_unit, is_base)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name, symbol=excluded.symbol,
                   minor_unit=excluded.minor_unit, is_base=excluded.is_base""",
            (code, name, symbol, minor_unit, is_base),
        )

    for order, (name, exclude_stats, color) in enumerate(EXPENSE_CATEGORIES):
        conn.execute(
            """INSERT INTO category (name, kind, color, exclude_stats, sort_order)
               VALUES (?, 'expense', ?, ?, ?)
               ON CONFLICT(name, kind) DO UPDATE SET
                   color=excluded.color, exclude_stats=excluded.exclude_stats""",
            (name, color, exclude_stats, order),
        )

    for order, (name, color) in enumerate(INCOME_CATEGORIES):
        conn.execute(
            """INSERT INTO category (name, kind, color, exclude_stats, sort_order)
               VALUES (?, 'income', ?, 0, ?)
               ON CONFLICT(name, kind) DO UPDATE SET color=excluded.color""",
            (name, color, order),
        )

    # Default self person (the account owner).
    conn.execute(
        """INSERT INTO person (name, initial, is_self)
           VALUES ('我', '我', 1)
           ON CONFLICT(name) DO NOTHING""",
    )

    # Tunable settings.
    _set_settings(conn, {
        "fiscal_day": "5",
        "base_currency": "CNY",
        "stale_rate_days": "7",
    })
    conn.commit()


def _set_settings(conn: sqlite3.Connection, items: dict) -> None:
    for key, value in items.items():
        conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def currency_id_map(conn: sqlite3.Connection) -> dict:
    """code/name -> currency row (id, minor_unit). Accepts either lookup key."""
    out = {}
    for row in conn.execute("SELECT id, code, name, minor_unit FROM currency"):
        out[row["code"]] = row
        out[row["name"]] = row
    return out
