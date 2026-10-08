-- Effective ("my") amount per transaction.
--
-- txn.amount_minor / base_amount_micro always keep the full amount actually
-- paid (the AA settlement math needs it). For a structured AA expense only my
-- own share is really my spending — settled or not (AA is usually settled soon,
-- and counting the fronted total meanwhile would distort the numbers) — so the
-- ledger, stats, budgets, the dashboard and the xlsx export all use it:
--
--   my_minor / my_base_micro  structured AA (and a self person exists): my owed
--                             share (0 if I was not a participant), base scaled
--                             by the same ratio (same rate). NULL otherwise.
--   eff_amount_minor          structured AA: my_minor; otherwise amount_minor.
--   eff_base_micro            same, in CNY micro.
--   eff_is_share              1 when eff_* is my share rather than the total.
--
-- A view, not cached columns, so it can never go stale when a txn is edited,
-- re-split, settled or re-rated. Every migration is re-run on startup, so
-- DROP + CREATE keeps the definition current.
DROP VIEW IF EXISTS txn_eff;
CREATE VIEW txn_eff AS
SELECT y.*,
       CASE WHEN y.eff_is_share = 1 THEN y.my_minor ELSE y.amount_minor END AS eff_amount_minor,
       CASE WHEN y.eff_is_share = 1 THEN y.my_base_micro ELSE y.base_amount_micro END AS eff_base_micro
FROM (
    SELECT x.*,
           CASE
               WHEN x.my_minor IS NULL OR x.base_amount_micro IS NULL THEN NULL
               WHEN x.my_minor = x.amount_minor THEN x.base_amount_micro
               WHEN x.amount_minor = 0 THEN 0
               ELSE CAST(ROUND(x.base_amount_micro * (x.my_minor * 1.0 / x.amount_minor)) AS INTEGER)
           END AS my_base_micro,
           CASE WHEN x.my_minor IS NOT NULL THEN 1 ELSE 0 END AS eff_is_share
    FROM (
        SELECT t.*,
               CASE WHEN t.is_aa = 1 AND EXISTS (SELECT 1 FROM person WHERE is_self = 1)
                    THEN COALESCE((SELECT tp.owed_amount_minor
                                   FROM   txn_participant tp
                                   JOIN   person p ON p.id = tp.person_id
                                   WHERE  tp.txn_id = t.id AND p.is_self = 1), 0)
               END AS my_minor
        FROM txn t
    ) x
) y;
