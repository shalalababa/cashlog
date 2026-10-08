"""Receipt calculator history: session <-> generated AA txn link, item
breakdown (labels usually blank), frozen sessions, backfill. Isolated temp DB."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import aa_service, db, seed, service  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_rcpt_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    me = conn.execute("SELECT id FROM person WHERE is_self = 1").fetchone()["id"]
    other = aa_service.create_person(conn, "LYH", write_json=False)["id"]
    return conn, me, other


def _session(conn, me, other, **kw):
    # Two unnamed items (the usual case) + tax: 11.00 total over 10.00 pretax.
    return aa_service.save_session(conn, {
        "name": "小票", "currency": "USD", "payer_id": me, "total_with_tax": "11.00",
        "items": [{"label": "", "pretax": "6.00", "person_ids": [me, other]},
                  {"label": None, "pretax": "4.00", "person_ids": [other]}], **kw,
    }, write_json=False)


def _generate(conn, sid):
    return aa_service.generate_txn_from_session(conn, sid, date="2024-03-10", content="小票 AA",
                                                write_json=False)


def test_generate_links_and_lists_receipt():
    conn, me, other = _env()
    s = _session(conn, me, other)
    assert s["txn_id"] is None
    t = _generate(conn, s["id"])
    assert aa_service.get_session(conn, s["id"])["txn_id"] == t["id"]
    rows = aa_service.list_receipt_txns(conn)
    assert [(r["txn_id"], r["session_id"], r["item_count"]) for r in rows] == [(t["id"], s["id"], 2)]
    assert rows[0]["amount"] == "11.00" and rows[0]["currency"] == "USD"


def test_item_breakdown_with_blank_labels():
    conn, me, other = _env()
    s = _session(conn, me, other)
    a, b = s["items"]
    assert a["label"] == "" and b["label"] is None          # blank names survive as-is
    assert a["pretax"] == "6.00" and a["with_tax"] == "6.60"
    assert b["with_tax"] == "4.40"
    assert {p["person_id"]: p["pretax"] for p in a["per_person"]} == {me: "3.00", other: "3.00"}
    assert {p["person_id"]: p["with_tax"] for p in a["per_person"]} == {me: "3.30", other: "3.30"}
    res = {r["person_id"]: (r["pretax"], r["amount"]) for r in s["result"]}
    assert res == {me: ("3.00", "3.30"), other: ("7.00", "7.70")}


def test_linked_session_is_frozen_and_generates_once():
    conn, me, other = _env()
    s = _session(conn, me, other)
    _generate(conn, s["id"])
    with pytest.raises(ValueError):
        _session(conn, me, other, id=s["id"])
    with pytest.raises(ValueError):
        _generate(conn, s["id"])


def test_deleting_txn_drops_link_only():
    conn, me, other = _env()
    s = _session(conn, me, other)
    t = _generate(conn, s["id"])
    service.delete_txn(conn, t["id"], write_json=False)
    assert aa_service.list_receipt_txns(conn) == []
    assert aa_service.get_session(conn, s["id"])["txn_id"] is None


def test_backfill_links_exact_match_only():
    conn, me, other = _env()
    s = _session(conn, me, other)
    t = _generate(conn, s["id"])
    dup = _session(conn, me, other)                          # identical, never generated
    conn.execute("DELETE FROM aa_session_txn"); conn.commit()  # pre-feature state
    # A look-alike txn with a different split must not be linked.
    other_t = service.create_txn(conn, {"date": "2024-03-11", "direction": "expense",
                                        "amount": "11.00", "currency": "USD", "content": "x"},
                                 write_json=False)["id"]
    aa_service.set_txn_aa(conn, other_t, me, [{"person_id": me, "fixed_amount": "5.50"},
                                              {"person_id": other, "fixed_amount": "5.50"}],
                          write_json=False)

    assert aa_service.link_existing_sessions(conn) == 1
    links = conn.execute("SELECT session_id, txn_id FROM aa_session_txn").fetchall()
    assert [tuple(r) for r in links] == [(dup["id"], t["id"])]   # newest identical session wins
    assert aa_service.link_existing_sessions(conn) == 0          # idempotent
