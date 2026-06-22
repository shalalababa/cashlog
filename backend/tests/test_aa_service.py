"""AA service layer — structured AA, settlement, calculator (isolated temp DB)."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import aa_service, db, jsonsync, seed, service  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_aas_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    return conn


def _person(conn, name):
    return aa_service.create_person(conn, name, write_json=False)["id"]


def _cny_expense(conn, amount, content="x"):
    return service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                                     "amount": amount, "currency": "CNY",
                                     "content": content}, write_json=False)["id"]


def _cny_income(conn, amount, content="x"):
    return service.create_txn(conn, {"date": "2024-03-05", "direction": "income",
                                     "amount": amount, "currency": "CNY",
                                     "content": content}, write_json=False)["id"]


def test_set_txn_aa_equal_split():
    conn = _env()
    a, b, c = _person(conn, "A"), _person(conn, "B"), _person(conn, "C")
    t = _cny_expense(conn, "30")
    aa_service.set_txn_aa(conn, t, payer_id=a,
                          participants=[{"person_id": a}, {"person_id": b}, {"person_id": c}],
                          write_json=False)
    info = aa_service.get_txn_aa(conn, t)
    assert info["is_aa"] and info["payer_id"] == a
    owed = sorted(p["owed"] for p in info["participants"])
    assert owed == ["10.00", "10.00", "10.00"]


def test_set_txn_aa_fixed_split():
    conn = _env()
    a, b, c = _person(conn, "A"), _person(conn, "B"), _person(conn, "C")
    t = _cny_expense(conn, "350")
    aa_service.set_txn_aa(conn, t, payer_id=c, participants=[
        {"person_id": a, "fixed_amount": "100"},
        {"person_id": b, "fixed_amount": "50"},
        {"person_id": c, "fixed_amount": "200"},
    ], write_json=False)
    owed = {p["name"]: p["owed"] for p in aa_service.get_txn_aa(conn, t)["participants"]}
    assert owed == {"A": "100.00", "B": "50.00", "C": "200.00"}


def test_settlement_matches_user_example():
    # A pays 20 (A&B each owe 10); B pays 40 (A&B each owe 20).
    # net A -10, B +10 -> A transfers B 10.
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t1 = _cny_expense(conn, "20", "晚餐")
    t2 = _cny_expense(conn, "40", "打车")
    aa_service.set_txn_aa(conn, t1, a, [{"person_id": a}, {"person_id": b}], write_json=False)
    aa_service.set_txn_aa(conn, t2, b, [{"person_id": a}, {"person_id": b}], write_json=False)

    groups = aa_service.compute_settlement(conn)
    assert len(groups) == 1
    g = groups[0]
    assert g["currency"] == "CNY"
    assert g["transfers"] == [{"from": a, "from_name": "A", "to": b, "to_name": "B", "amount": "10.00"}]


def test_settle_marks_rows_settled():
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t = _cny_expense(conn, "20")
    aa_service.set_txn_aa(conn, t, a, [{"person_id": a}, {"person_id": b}], write_json=False)
    assert len(aa_service.list_unsettled(conn)) == 1
    aa_service.settle(conn, [t], write_json=False)
    assert aa_service.list_unsettled(conn) == []


def test_candidates_and_batch_structure():
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t1 = _cny_expense(conn, "30", "Costco AA 采购")
    t2 = _cny_expense(conn, "10", "普通消费")
    cands = aa_service.candidates(conn)
    assert [c["id"] for c in cands] == [t1]      # only the AA-text one
    aa_service.batch_structure(conn, [t1], payer_id=a, participant_ids=[a, b], write_json=False)
    assert aa_service.candidates(conn) == []     # now structured
    info = aa_service.get_txn_aa(conn, t1)
    assert info["is_aa"] and len(info["participants"]) == 2


def test_calculator_session_and_generate():
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    s = aa_service.save_session(conn, {
        "name": "超市小票", "currency": "CNY", "payer_id": a, "total_with_tax": "50",
        "items": [
            {"label": "牛奶", "pretax": "10", "person_ids": [a]},
            {"label": "零食", "pretax": "30", "person_ids": [b]},
        ],
    }, write_json=False)
    res = {r["name"]: r["amount"] for r in s["result"]}
    assert res == {"A": "12.50", "B": "37.50"}      # proportional tax
    assert s["tax_amount"] == "10.00"

    txn = aa_service.generate_txn_from_session(conn, s["id"], date="2024-03-05",
                                               content="超市", write_json=False)
    assert txn["is_aa"] and txn["amount"] == "50.00"
    info = aa_service.get_txn_aa(conn, txn["id"])
    assert sorted(p["owed"] for p in info["participants"]) == ["12.50", "37.50"]
    assert info["payer_id"] == a


# --- review fixes: AA settlement boundaries -------------------------------------
def test_set_txn_aa_requires_payer():
    # No-payer AA used to be accepted and then show "已平衡" (only debtors, no
    # creditor). It must be rejected outright.
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t = _cny_expense(conn, "20")
    with pytest.raises(ValueError):
        aa_service.set_txn_aa(conn, t, payer_id=None,
                              participants=[{"person_id": a}, {"person_id": b}],
                              write_json=False)
    assert aa_service.get_txn_aa(conn, t)["is_aa"] is False   # nothing persisted


def test_set_txn_aa_rejects_income():
    # Income / refund "AA" would settle the wrong direction.
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t = _cny_income(conn, "20", "亚马逊 AA 退款")
    with pytest.raises(ValueError):
        aa_service.set_txn_aa(conn, t, payer_id=a,
                              participants=[{"person_id": a}, {"person_id": b}],
                              write_json=False)


def test_set_txn_aa_rejects_unknown_person():
    # Bad person id must surface as a clean ValueError (-> 400), not a leaked
    # SQLite FOREIGN KEY IntegrityError.
    conn = _env()
    a = _person(conn, "A")
    t = _cny_expense(conn, "20")
    with pytest.raises(ValueError):
        aa_service.set_txn_aa(conn, t, payer_id=a,
                              participants=[{"person_id": a}, {"person_id": 999999}],
                              write_json=False)
    with pytest.raises(ValueError):                          # unknown payer too
        aa_service.set_txn_aa(conn, t, payer_id=999999,
                              participants=[{"person_id": a}], write_json=False)


def test_set_txn_aa_rejects_duplicate_participant():
    conn = _env()
    a = _person(conn, "A")
    t = _cny_expense(conn, "20")
    with pytest.raises(ValueError):
        aa_service.set_txn_aa(conn, t, payer_id=a,
                              participants=[{"person_id": a}, {"person_id": a}],
                              write_json=False)


def test_candidates_excludes_income():
    conn = _env()
    t_exp = _cny_expense(conn, "30", "Costco AA 采购")
    _cny_income(conn, "20", "亚马逊 AA 退款")          # must NOT be a candidate
    assert [c["id"] for c in aa_service.candidates(conn)] == [t_exp]


def test_batch_structure_rejects_income_atomically():
    conn = _env()
    a, b = _person(conn, "A"), _person(conn, "B")
    t_exp = _cny_expense(conn, "30", "Costco AA")
    t_inc = _cny_income(conn, "20", "AA 退款")
    with pytest.raises(ValueError):
        aa_service.batch_structure(conn, [t_exp, t_inc], payer_id=a,
                                   participant_ids=[a, b], write_json=False)
    # pre-flight failed before mutating, so the valid row is untouched too.
    assert aa_service.get_txn_aa(conn, t_exp)["is_aa"] is False


def test_update_person_duplicate_name_is_valueerror():
    # Renaming onto an existing name must be a clean ValueError (-> 400), not a
    # leaked SQLite IntegrityError.
    conn = _env()
    _person(conn, "甲")
    b = _person(conn, "乙")
    with pytest.raises(ValueError):
        aa_service.update_person(conn, b, {"name": "甲"}, write_json=False)


def test_create_person_writes_json_mirror():
    conn = _env()
    mirror = jsonsync.mirror_path_for(conn)
    assert not mirror.exists()
    aa_service.create_person(conn, "镜像人")            # default write_json=True
    assert mirror.exists()
    assert "镜像人" in mirror.read_text(encoding="utf-8")


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
