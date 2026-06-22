"""Statistics engine — fiscal-month totals, breakdown, trend (isolated temp DB)."""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import db, seed, service, stats  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_stats_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    return conn


def _cat(conn, name):
    return conn.execute("SELECT id FROM category WHERE name=? AND kind='expense'",
                        (name,)).fetchone()["id"]


def _ccy(conn, code):
    return conn.execute("SELECT id FROM currency WHERE code=?", (code,)).fetchone()["id"]


def _rate(conn, code, rate_date, rate):
    conn.execute("INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base) VALUES (?,?,?)",
                 (_ccy(conn, code), rate_date, str(rate)))
    conn.commit()


def _expense(conn, d, amount, *, currency="CNY", category=None, content="x"):
    return service.create_txn(conn, {
        "date": d, "direction": "expense", "amount": amount, "currency": currency,
        "content": content, "category_id": _cat(conn, category) if category else None,
    }, write_json=False)["id"]


def _fiscal_month(conn, period_end, cc_usd, ccy="USD"):
    conn.execute(
        """INSERT INTO fiscal_month (period_end, credit_card_amount_minor, credit_card_ccy_id)
           VALUES (?, ?, ?)""",
        (period_end, int(round(float(cc_usd) * 100)), _ccy(conn, ccy)))
    conn.commit()


# --- date math --------------------------------------------------------------
def test_fiscal_range_is_half_open_prev_5th_to_this_5th():
    assert stats.fiscal_range("2024-03-05") == ("2024-02-05", "2024-03-05")


def test_edate_clamps_to_month_end():
    assert stats.edate(date(2024, 3, 31), -1) == date(2024, 2, 29)   # leap-year clamp
    assert stats.edate(date(2024, 1, 15), -1) == date(2023, 12, 15)  # year rollover


# --- fiscal-month engine (replicates 统计 SUMIFS) ----------------------------
def test_fiscal_month_total_excludes_flagged_and_respects_boundaries():
    conn = _env()
    _rate(conn, "USD", "2024-03-01", "7")                    # 当日汇率 for 2024-03-05
    # window is [2024-02-05, 2024-03-05)
    _expense(conn, "2024-02-05", "100")                      # start boundary -> included
    _expense(conn, "2024-02-10", "30")                       # uncategorized   -> included
    _expense(conn, "2024-02-20", "50", category="学费")      # exclude_stats   -> excluded
    _expense(conn, "2024-03-05", "999")                      # end boundary    -> excluded (<)
    _expense(conn, "2024-01-31", "70")                       # before window   -> excluded
    _fiscal_month(conn, "2024-03-05", "10")                  # 10 USD credit card

    rows = stats.fiscal_months(conn)
    assert len(rows) == 1
    fm = rows[0]
    assert fm["range_start"] == "2024-02-05" and fm["range_end"] == "2024-03-04"
    assert fm["total_cny"] == 130.0                          # 100 + 30
    assert fm["total_usd"] == round(130 / 7, 2)              # 美元换算 = B/H
    assert fm["credit_card"] == 10.0
    assert fm["credit_card_cny"] == 70.0                     # 10 USD * 7
    assert fm["ratio"] == pytest.approx(70 / 130)            # 占比, may exceed 1 elsewhere
    assert fm["usd_rate"] == 7.0


def test_fiscal_ratio_can_exceed_one():
    conn = _env()
    _rate(conn, "USD", "2024-03-01", "7")
    _expense(conn, "2024-02-10", "100")                      # 100 CNY total
    _fiscal_month(conn, "2024-03-05", "100")                 # 100 USD -> 700 CNY credit card
    fm = stats.fiscal_months(conn)[0]
    assert fm["ratio"] == pytest.approx(7.0)                 # 700 / 100 = 700%


# --- category breakdown -----------------------------------------------------
def test_category_breakdown_buckets_uncategorized_and_flags_excluded():
    conn = _env()
    _expense(conn, "2024-02-10", "40", category="饮食")
    _expense(conn, "2024-02-11", "60", category="饮食")
    _expense(conn, "2024-02-12", "25")                       # uncategorized
    _expense(conn, "2024-02-13", "15", category="学费")      # excluded flag, still listed
    _expense(conn, "2024-05-01", "999", category="饮食")     # out of range

    rows = stats.category_breakdown(conn, "2024-02-01", "2024-02-28")
    by = {r["category"]: r for r in rows}
    assert by["饮食"]["total"] == 100.0 and by["饮食"]["count"] == 2
    assert by["未分类"]["total"] == 25.0 and by["未分类"]["category_id"] is None
    assert by["学费"]["exclude_stats"] is True
    assert "饮食" == rows[0]["category"]                     # sorted by total desc


# --- category trend ---------------------------------------------------------
def test_category_trend_month_is_gap_filled_and_aligned():
    conn = _env()
    _expense(conn, "2024-01-10", "10", category="饮食")
    _expense(conn, "2024-03-10", "30", category="饮食")
    _expense(conn, "2024-03-15", "5", category="交通")

    res = stats.category_trend(conn, "2024-01-01", "2024-03-31", granularity="month")
    assert res["periods"] == ["2024-01", "2024-02", "2024-03"]   # Feb gap-filled
    series = {s["category"]: s["values"] for s in res["series"]}
    assert series["饮食"] == [10.0, 0.0, 30.0]
    assert series["交通"] == [0.0, 0.0, 5.0]


def test_category_trend_rejects_bad_granularity():
    conn = _env()
    with pytest.raises(ValueError):
        stats.category_trend(conn, "2024-01-01", "2024-03-31", granularity="year")


def test_stats_reject_bad_dates():
    conn = _env()
    with pytest.raises(ValueError):
        stats.category_breakdown(conn, "nope", "2024-01-01")


def test_stats_reject_bad_direction():
    # A bad direction must raise (-> 400), not silently return empty data.
    conn = _env()
    with pytest.raises(ValueError):
        stats.category_breakdown(conn, "2024-01-01", "2024-03-31", direction="oops")
    with pytest.raises(ValueError):
        stats.category_trend(conn, "2024-01-01", "2024-03-31", direction="oops")


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
