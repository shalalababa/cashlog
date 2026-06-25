"""Dashboard aggregation — month compare, top categories, budget, AA (temp DB)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import aa_service, budgets, dashboard, db, seed, service  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_dash_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    return conn


def _cat(conn, name):
    return conn.execute("SELECT id FROM category WHERE name=? AND kind='expense'",
                        (name,)).fetchone()["id"]


def _person(conn, name):
    return aa_service.create_person(conn, name, write_json=False)["id"]


def _rate(conn, code, rate_date, rate):
    ccy = conn.execute("SELECT id FROM currency WHERE code=?", (code,)).fetchone()["id"]
    conn.execute("INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base) VALUES (?,?,?)",
                 (ccy, rate_date, str(rate)))
    conn.commit()


def _expense(conn, d, amount, *, category=None, content="x"):
    return service.create_txn(conn, {
        "date": d, "direction": "expense", "amount": amount, "currency": "CNY",
        "content": content, "category_id": _cat(conn, category) if category else None,
    }, write_json=False)["id"]


# today=2024-03-22 -> current close 2024-04-05 window [2024-03-05, 2024-04-05);
# previous close 2024-03-05 window [2024-02-05, 2024-03-05).
TODAY = "2024-03-22"


def test_current_vs_previous_month_delta():
    conn = _env()
    _expense(conn, "2024-03-10", "300", category="饮食")   # current month
    _expense(conn, "2024-02-10", "200", category="饮食")   # previous month
    d = dashboard.dashboard(conn, today=TODAY)
    assert d["current"]["period_end"] == "2024-04-05"
    assert d["current"]["total_cny"] == 300.0
    assert d["previous"]["total_cny"] == 200.0
    assert d["current"]["delta"] == 100.0
    assert d["current"]["delta_pct"] == pytest.approx(100 / 200)


def test_month_summary_includes_usd_conversion():
    conn = _env()
    _rate(conn, "USD", TODAY, "7.50")
    _expense(conn, "2024-03-10", "150")
    d = dashboard.dashboard(conn, today=TODAY)
    assert d["current"]["usd_rate"] == 7.5
    assert d["current"]["usd_rate_date"] == TODAY
    assert d["current"]["rate_lookup_date"] == TODAY
    assert d["current"]["total_usd"] == 20.0
    assert d["current"]["rate_stale"] is False


def test_current_month_usd_conversion_does_not_use_future_close_rate():
    conn = _env()
    _rate(conn, "USD", TODAY, "7.50")
    _rate(conn, "USD", "2024-04-05", "10.00")
    _expense(conn, "2024-03-10", "150")
    d = dashboard.dashboard(conn, today=TODAY)
    assert d["current"]["period_end"] == "2024-04-05"
    assert d["current"]["usd_rate"] == 7.5
    assert d["current"]["usd_rate_date"] == TODAY
    assert d["current"]["total_usd"] == 20.0


def test_cumulative_compare_aligns_current_and_previous_by_elapsed_day():
    conn = _env()
    _expense(conn, "2024-03-05", "10")
    _expense(conn, "2024-03-07", "30")
    _expense(conn, "2024-02-05", "5")
    _expense(conn, "2024-02-06", "20")
    d = dashboard.dashboard(conn, today="2024-03-07")
    assert d["cumulative"]["days"] == [1, 2, 3]
    assert d["cumulative"]["current"]["range_start"] == "2024-03-05"
    assert d["cumulative"]["current"]["range_end"] == "2024-03-07"
    assert d["cumulative"]["current"]["values"] == [10.0, 10.0, 40.0]
    assert d["cumulative"]["previous"]["range_start"] == "2024-02-05"
    assert d["cumulative"]["previous"]["range_end"] == "2024-02-07"
    assert d["cumulative"]["previous"]["values"] == [5.0, 25.0, 25.0]


def test_top_categories_excludes_flagged_and_sorts():
    conn = _env()
    _expense(conn, "2024-03-10", "300", category="饮食")
    _expense(conn, "2024-03-11", "120", category="交通")
    _expense(conn, "2024-03-12", "500", category="学费")    # exclude_stats -> not a top category
    top = dashboard.dashboard(conn, today=TODAY)["top_categories"]
    names = [c["category"] for c in top]
    assert names == ["饮食", "交通"] and "学费" not in names


def test_dashboard_embeds_budget_status():
    conn = _env()
    _expense(conn, "2024-03-10", "150", category="饮食")
    budgets.set_budget(conn, category_id=None, amount="500", write_json=False)
    d = dashboard.dashboard(conn, today=TODAY)
    assert d["budget"]["period_end"] == "2024-04-05"
    assert d["budget"]["overall"]["limit"] == "500.00"
    assert d["budget"]["overall"]["actual"] == "150.00"


def test_aa_unsettled_summary():
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t = _expense(conn, "2024-03-10", "100", category="饮食", content="dinner AA")
    aa_service.set_txn_aa(conn, t, payer_id=a,
                          participants=[{"person_id": a}, {"person_id": b}], write_json=False)
    summary = dashboard.dashboard(conn, today=TODAY)["aa_unsettled"]
    assert summary["count"] == 1
    assert summary["by_currency"][0]["currency"] == "CNY"
    assert summary["by_currency"][0]["amount"] == "100.00"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
