-- P6 budgets — additive migration.
--
-- A single overall monthly target (category_id IS NULL) plus optional per-category
-- targets. Each target is either an absolute CNY amount (amount_micro, CNY * 1e6)
-- or a percentage of the overall budget (percent, decimal string). Budgets are a
-- read-only input to the dashboard / budget views; they never feed back into the
-- fiscal-month statistics (统计 stays exactly as the workbook computed it).
--
-- Every statement is idempotent (IF NOT EXISTS) so this can be applied to a DB
-- created before P6 without touching existing data. Applied by db.ensure_schema
-- on top of the docs/schema.sql baseline.

CREATE TABLE IF NOT EXISTS budget (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER REFERENCES category(id) ON DELETE CASCADE,  -- NULL = overall budget
    amount_type  TEXT    NOT NULL DEFAULT 'absolute' CHECK (amount_type IN ('absolute','percent')),
    amount_micro INTEGER CHECK (amount_micro IS NULL OR amount_micro >= 0),  -- absolute: CNY * 1,000,000
    percent      TEXT,                                                       -- percent of overall, decimal string
    note         TEXT,
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- absolute rows carry amount_micro; percent rows carry percent.
    CHECK ((amount_type = 'absolute' AND amount_micro IS NOT NULL)
        OR (amount_type = 'percent'  AND percent IS NOT NULL AND CAST(percent AS REAL) >= 0)),
    -- the overall budget is a share base, so it must itself be absolute.
    CHECK (category_id IS NOT NULL OR amount_type = 'absolute')
);

-- At most one budget per category, and at most one overall (NULL-category) row.
-- The overall index keys on a constant expression (1 for every NULL-category row)
-- so the partial unique index collapses them to a single allowed row — a plain
-- UNIQUE(category_id) would not, since NULLs are distinct.
CREATE UNIQUE INDEX IF NOT EXISTS idx_budget_category ON budget (category_id)        WHERE category_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_budget_overall  ON budget ((category_id IS NULL)) WHERE category_id IS NULL;
