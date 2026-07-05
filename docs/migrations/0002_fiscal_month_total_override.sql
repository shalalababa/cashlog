-- P7 fiscal-month manual total override.
--
-- The old fiscal_month table stores only the manual credit-card input; the
-- headline fiscal total is derived from txn rows. Editing that derived total
-- needs a separate override so the default path can continue to recalculate
-- from transactions, while edited months stay stable and auditable.

CREATE TABLE IF NOT EXISTS fiscal_month_total_override (
    period_end           TEXT PRIMARY KEY REFERENCES fiscal_month(period_end) ON DELETE CASCADE,
    total_override_micro INTEGER NOT NULL,
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
