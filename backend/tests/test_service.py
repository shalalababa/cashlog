"""Service layer (CRUD, listing, autocomplete, rate) — isolated temp DB."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import db, seed, service  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_svc_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    # a couple of USD rates so conversion works
    usd = conn.execute("SELECT id FROM currency WHERE code='USD'").fetchone()["id"]
    conn.execute("INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base) VALUES (?,?,?)",
                 (usd, "2024-03-01", "7.20"))
    conn.commit()
    return conn


def _ecat(conn, name="饮食"):
    return conn.execute("SELECT id FROM category WHERE name=? AND kind='expense'", (name,)).fetchone()["id"]


def test_create_converts_and_lists():
    conn = _env()
    t = service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                                  "amount": "5.51", "currency": "USD",
                                  "content": "ChatGPT订阅 月付", "category_id": _ecat(conn)})
    assert t["amount"] == "5.51"
    assert t["base_cny"] == "39.67"          # 5.51 * 7.20
    assert t["has_rate"] is True
    listing = service.list_txns(conn, direction="expense")
    assert listing["total"] == 1
    assert listing["items"][0]["content"] == "ChatGPT订阅 月付"


def test_update_and_delete():
    conn = _env()
    t = service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                                  "amount": "10", "currency": "CNY", "content": "x"})
    t2 = service.update_txn(conn, t["id"], {"date": "2024-03-05", "direction": "expense",
                                            "amount": "12", "currency": "CNY", "content": "y"})
    assert t2["amount"] == "12.00" and t2["content"] == "y" and t2["revision"] == 2
    assert service.delete_txn(conn, t["id"]) is True
    assert service.list_txns(conn)["total"] == 0


def test_category_kind_mismatch_is_rejected():
    conn = _env()
    income_cat = conn.execute("SELECT id FROM category WHERE kind='income' LIMIT 1").fetchone()["id"]
    try:
        service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                                  "amount": "1", "currency": "CNY", "category_id": income_cat})
        raised = False
    except ValueError:
        raised = True
    assert raised, "expense txn with an income category must be rejected by the trigger"


def test_autocomplete_prefix_and_uniqueness():
    conn = _env()
    ec = _ecat(conn)
    for content in ["ChatGPT订阅 月付", "ChatGPT订阅 月付", "ChatGPT订阅 年付"]:
        service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                                  "amount": "1", "currency": "CNY", "content": content, "category_id": ec})
    broad = service.autocomplete(conn, "expense", "Chat")
    assert {c["content"] for c in broad} == {"ChatGPT订阅 月付", "ChatGPT订阅 年付"}
    assert broad[0]["content"] == "ChatGPT订阅 月付"   # higher frequency first
    narrow = service.autocomplete(conn, "expense", "ChatGPT订阅 月")
    assert [c["content"] for c in narrow] == ["ChatGPT订阅 月付"]


def test_invalid_date_is_rejected():
    conn = _env()
    for bad in ("bad-date", "2024-13-01", "2024-02-30", ""):
        raised = False
        try:
            service.create_txn(conn, {"date": bad, "direction": "expense",
                                      "amount": "1", "currency": "CNY"}, write_json=False)
        except ValueError:
            raised = True
        assert raised, f"date {bad!r} should be rejected (base-currency path skips rate parsing)"


def test_mutation_does_not_touch_real_json_mirror():
    # Regression: service mutations on a temp DB must mirror next to that DB,
    # never overwrite the real backend/data/cashlog.json.
    from cashlog import config, jsonsync
    real = config.JSON_MIRROR_PATH
    before = real.read_bytes() if real.exists() else None
    conn = _env()
    service.create_txn(conn, {"date": "2024-03-05", "direction": "expense",
                              "amount": "1", "currency": "CNY"})  # write_json default True
    after = real.read_bytes() if real.exists() else None
    assert after == before, "real JSON mirror must be untouched by a temp-DB mutation"
    assert jsonsync.mirror_path_for(conn).exists(), "mirror should be written next to the temp DB"


def test_rate_lookup_and_staleness():
    conn = _env()
    fresh = service.rate_for(conn, "USD", "2024-03-03")
    assert fresh["found"] and fresh["rate"] == "7.20" and fresh["stale"] is False
    stale = service.rate_for(conn, "USD", "2024-05-01")
    assert stale["found"] and stale["stale"] is True   # >7 days past 2024-03-01


def test_rate_rejects_bad_date():
    conn = _env()
    # CNY + bad date previously returned found:true rate:1 (base path skips parsing).
    for bad in ("bad-date", "2024-13-40"):
        raised = False
        try:
            service.rate_for(conn, "CNY", bad)
        except ValueError:
            raised = True
        assert raised, f"rate_for must reject date {bad!r}"


def test_mirror_path_for_inmemory_raises():
    import sqlite3
    from cashlog import jsonsync
    mem = sqlite3.connect(":memory:")
    try:
        jsonsync.mirror_path_for(mem)
        raised = False
    except ValueError:
        raised = True
    finally:
        mem.close()
    assert raised, "in-memory DB must not fall back to the real mirror path"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
