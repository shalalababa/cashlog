"""Budgets — overall/category, absolute/percent, progress (isolated temp DB)."""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import budgets, db, seed, service, stats  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_budget_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    return conn


def _cat(conn, name):
    return conn.execute("SELECT id FROM category WHERE name=? AND kind='expense'",
                        (name,)).fetchone()["id"]


def _expense(conn, d, amount, *, category=None, content="x"):
    return service.create_txn(conn, {
        "date": d, "direction": "expense", "amount": amount, "currency": "CNY",
        "content": content, "category_id": _cat(conn, category) if category else None,
    }, write_json=False)["id"]


# --- date math --------------------------------------------------------------
def test_current_fiscal_end_uses_half_open_5th():
    assert stats.current_fiscal_end(date(2024, 3, 22)) == date(2024, 4, 5)  # after the 5th -> next
    assert stats.current_fiscal_end(date(2024, 3, 3)) == date(2024, 3, 5)   # before the 5th -> this
    assert stats.current_fiscal_end(date(2024, 3, 5)) == date(2024, 4, 5)   # on the 5th -> next


# --- CRUD -------------------------------------------------------------------
def test_set_and_list_overall_and_category():
    conn = _env()
    budgets.set_budget(conn, category_id=None, amount="3000", write_json=False)
    budgets.set_budget(conn, category_id=_cat(conn, "饮食"), amount="800", write_json=False)
    data = budgets.list_budgets(conn)
    assert data["overall"]["amount"] == "3000.00"
    assert len(data["categories"]) == 1
    assert data["categories"][0]["category"] == "饮食" and data["categories"][0]["amount"] == "800.00"


def test_set_budget_is_upsert_not_duplicate():
    conn = _env()
    budgets.set_budget(conn, category_id=None, amount="3000", write_json=False)
    budgets.set_budget(conn, category_id=None, amount="3500", write_json=False)
    data = budgets.list_budgets(conn)
    assert data["overall"]["amount"] == "3500.00"
    assert conn.execute("SELECT COUNT(*) AS n FROM budget WHERE category_id IS NULL").fetchone()["n"] == 1


def test_set_budget_accepts_usd_input_at_period_rate():
    conn = _env()
    usd = conn.execute("SELECT id FROM currency WHERE code='USD'").fetchone()["id"]
    conn.execute("INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base) VALUES (?,?,?)",
                 (usd, "2024-03-05", "7.20"))
    conn.commit()
    budgets.set_budget(conn, category_id=None, amount="100", amount_currency="USD",
                       period_end="2024-03-05", write_json=False)
    assert budgets.list_budgets(conn)["overall"]["amount"] == "720.00"


def test_overall_must_be_absolute():
    conn = _env()
    with pytest.raises(ValueError):
        budgets.set_budget(conn, category_id=None, amount_type="percent", percent="50", write_json=False)


def test_set_budget_rejects_unknown_category():
    conn = _env()
    with pytest.raises(ValueError):
        budgets.set_budget(conn, category_id=999999, amount="100", write_json=False)


def test_delete_budget():
    conn = _env()
    b = budgets.set_budget(conn, category_id=_cat(conn, "饮食"), amount="100", write_json=False)
    assert budgets.delete_budget(conn, b["id"], write_json=False) is True
    assert budgets.list_budgets(conn)["categories"] == []


# --- progress ---------------------------------------------------------------
def _seed_window(conn):
    # current fiscal window for 2024-03-05 close is [2024-02-05, 2024-03-05)
    _expense(conn, "2024-02-10", "120", category="饮食")
    _expense(conn, "2024-02-12", "80", category="交通")
    _expense(conn, "2024-02-15", "50", category="学费")     # exclude_stats
    _expense(conn, "2024-03-05", "999", category="饮食")    # end boundary -> excluded


def test_overall_progress_excludes_flagged_categories():
    conn = _env()
    _seed_window(conn)
    budgets.set_budget(conn, category_id=None, amount="300", write_json=False)
    st = budgets.budget_status(conn, "2024-03-05")
    assert st["overall"]["actual"] == "200.00"        # 120 + 80, 学费 excluded, boundary excluded
    assert st["overall"]["pct"] == pytest.approx(200 / 300)
    assert st["overall"]["remaining"] == "100.00" and st["overall"]["over"] is False


def test_category_absolute_progress_and_over():
    conn = _env()
    _seed_window(conn)
    budgets.set_budget(conn, category_id=_cat(conn, "饮食"), amount="100", write_json=False)
    cat = budgets.budget_status(conn, "2024-03-05")["categories"][0]
    assert cat["category"] == "饮食"
    assert cat["actual"] == "120.00" and cat["over"] is True
    assert cat["pct"] == pytest.approx(120 / 100)


def test_category_budget_actual_tracks_excluded_category():
    # A budget set on 学费 (exclude_stats) still tracks that category's spend,
    # even though it is excluded from the overall/fiscal total.
    conn = _env()
    _seed_window(conn)
    budgets.set_budget(conn, category_id=_cat(conn, "学费"), amount="60", write_json=False)
    cat = budgets.budget_status(conn, "2024-03-05")["categories"][0]
    assert cat["category"] == "学费" and cat["actual"] == "50.00" and cat["over"] is False


def test_percent_budget_resolves_to_share_of_overall():
    conn = _env()
    _seed_window(conn)
    budgets.set_budget(conn, category_id=None, amount="300", write_json=False)
    budgets.set_budget(conn, category_id=_cat(conn, "交通"), amount_type="percent",
                       percent="25", write_json=False)   # 25% of 300 = 75
    cat = next(c for c in budgets.budget_status(conn, "2024-03-05")["categories"]
               if c["category"] == "交通")
    assert cat["limit"] == "75.00"
    assert cat["actual"] == "80.00" and cat["over"] is True   # 80 > 75


def test_percent_budget_without_overall_is_unresolved():
    conn = _env()
    _seed_window(conn)
    budgets.set_budget(conn, category_id=_cat(conn, "交通"), amount_type="percent",
                       percent="25", write_json=False)
    cat = budgets.budget_status(conn, "2024-03-05")["categories"][0]
    assert cat["limit"] is None and cat["pct"] is None and cat["over"] is False


def test_budget_status_reports_window_and_has_overall():
    conn = _env()
    budgets.set_budget(conn, category_id=None, amount="300", write_json=False)
    st = budgets.budget_status(conn, "2024-03-05")
    assert st["range_start"] == "2024-02-05" and st["range_end"] == "2024-03-04"
    assert st["has_overall"] is True


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
