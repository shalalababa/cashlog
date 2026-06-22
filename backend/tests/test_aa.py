"""AA math core — pure-function tests."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import aa  # noqa: E402


def test_allocate_sums_exactly():
    # 1000 split 3 ways -> 334/333/333, exact sum
    parts = aa.allocate(1000, [Decimal(1), Decimal(1), Decimal(1)])
    assert sum(parts) == 1000
    assert sorted(parts) == [333, 333, 334]


def test_allocate_weighted():
    parts = aa.allocate(5000, [Decimal(10), Decimal(30)])  # Amazon 50, 10 vs 30
    assert parts == [1250, 3750]


def test_compute_owed_equal_and_fixed():
    eq = aa.compute_owed(1000, [{"person_id": 1}, {"person_id": 2}, {"person_id": 3}])
    assert sum(eq) == 1000
    fixed = aa.compute_owed(35000, [
        {"person_id": 1, "fixed_amount_minor": 10000},
        {"person_id": 2, "fixed_amount_minor": 5000},
        {"person_id": 3, "fixed_amount_minor": 20000},
    ])
    assert fixed == [10000, 5000, 20000]


def test_compute_owed_fixed_must_sum():
    raised = False
    try:
        aa.compute_owed(1000, [{"person_id": 1, "fixed_amount_minor": 400},
                               {"person_id": 2, "fixed_amount_minor": 400}])
    except ValueError:
        raised = True
    assert raised


def test_min_cash_flow_two_party():
    # The user's example: A net -10, B net +10  -> A pays B 10
    transfers = aa.min_cash_flow({1: -1000, 2: 1000})
    assert transfers == [{"from": 1, "to": 2, "amount_minor": 1000}]


def test_min_cash_flow_simplifies_chain():
    # A owes 10, B square, C is owed 10 ; plus B owes 5, A is owed 5 ...
    # net: A -5, B -5, C +10  -> two transfers totalling 10
    transfers = aa.min_cash_flow({1: -500, 2: -500, 3: 1000})
    assert sum(t["amount_minor"] for t in transfers) == 1000
    assert all(t["to"] == 3 for t in transfers)
    assert len(transfers) == 2


def test_min_cash_flow_balanced_is_empty():
    assert aa.min_cash_flow({1: 0, 2: 0}) == []


def test_compute_session_proportional_tax():
    # total 50.00, items pretax 10.00 (A) and 30.00 (B) -> 12.50 / 37.50
    out = aa.compute_session(5000, [
        {"pretax_minor": 1000, "shares": [{"person_id": 1}]},
        {"pretax_minor": 3000, "shares": [{"person_id": 2}]},
    ])
    assert out == {1: 1250, 2: 3750}
    assert sum(out.values()) == 5000


def test_compute_session_shared_items_sum_to_total():
    # shared item between two people + individual items; result must sum to total
    out = aa.compute_session(10000, [
        {"pretax_minor": 4000, "shares": [{"person_id": 1}, {"person_id": 2}]},  # split 2000/2000
        {"pretax_minor": 2000, "shares": [{"person_id": 1}]},
        {"pretax_minor": 3000, "shares": [{"person_id": 3}]},
    ])
    assert sum(out.values()) == 10000
    assert set(out) == {1, 2, 3}


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
