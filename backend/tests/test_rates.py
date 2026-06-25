"""Exchange-rate refresh: fetch, upsert and recompute cached conversions."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from cashlog import db, rates, seed, service  # noqa: E402


def _env():
    d = Path(tempfile.mkdtemp(prefix="cashlog_rates_"))
    db.init_db(d / "t.db", reset=True)
    conn = db.connect(d / "t.db")
    seed.seed(conn)
    usd = conn.execute("SELECT id FROM currency WHERE code='USD'").fetchone()["id"]
    conn.execute(
        "INSERT INTO exchange_rate (currency_id, rate_date, rate_to_base) VALUES (?,?,?)",
        (usd, "2024-01-01", "7.00"),
    )
    conn.commit()
    return conn


def test_refresh_rates_upserts_and_recomputes_stale_txns():
    conn = _env()
    txn = service.create_txn(conn, {
        "date": "2024-02-10", "direction": "expense", "amount": "10",
        "currency": "USD", "content": "stale usd",
    }, write_json=False)
    assert txn["rate_used"] == "7.00"
    assert txn["rate_stale"] is True
    assert txn["base_cny"] == "70.00"

    def fake_fetch(base: str, quote: str, start: str, end: str):
        assert (base, quote, start, end) == ("USD", "CNY", "2024-02-01", "2024-02-10")
        return [{"date": "2024-02-09", "rate": "7.20"}]

    out = rates.refresh_rates(
        conn, currency_codes=["USD"], start_date="2024-02-01", end_date="2024-02-10",
        fetcher=fake_fetch, write_json=False,
    )
    assert out["inserted"] == 1
    assert out["recomputed_txns"] == 1

    refreshed = service.get_txn(conn, txn["id"])
    assert refreshed["rate_used"] == "7.2"
    assert refreshed["rate_date_used"] == "2024-02-09"
    assert refreshed["rate_stale_days"] == 1
    assert refreshed["rate_stale"] is False
    assert refreshed["base_cny"] == "72.00"
    assert rates.rate_status(conn)["stale_txn_count"] == 0


def test_refresh_rates_rejects_bad_provider_rows():
    conn = _env()

    def bad_fetch(_base: str, _quote: str, _start: str, _end: str):
        return [{"date": "2024-02-09", "rate": "-1"}]

    with pytest.raises(ValueError):
        rates.refresh_rates(
            conn, currency_codes=["USD"], start_date="2024-02-01",
            end_date="2024-02-10", fetcher=bad_fetch, write_json=False,
        )
