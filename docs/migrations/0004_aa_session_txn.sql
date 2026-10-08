-- Which AA transaction a receipt-calculator session generated.
--
-- Keeps the receipt's line items + per-person split as the auditable history
-- behind that txn (shown under AA -> 小票细项). One session generates at most one
-- txn and vice versa. Deleting the txn drops the link (the session stays);
-- a linked session is frozen (aa_service refuses to edit it) so its items can
-- never drift from the txn they produced.
CREATE TABLE IF NOT EXISTS aa_session_txn (
    session_id  INTEGER PRIMARY KEY REFERENCES aa_session(id) ON DELETE CASCADE,
    txn_id      INTEGER NOT NULL UNIQUE REFERENCES txn(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
