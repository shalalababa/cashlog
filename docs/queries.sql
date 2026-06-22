-- Representative application queries for Cashlog.
-- All user-provided values must be bound parameters.

-- 1) Rate lookup: most recent rate for a currency on-or-before a date.
--    Mirrors the workbook's INDEX/MATCH/MAX array formula.
SELECT rate_to_base,
       rate_date
FROM   exchange_rate
WHERE  currency_id = :currency_id
  AND  rate_date <= :on_date
ORDER BY rate_date DESC
LIMIT 1;

-- 2) Fiscal-month total expense in CNY micro-units.
--    Window is [period_end - 1 month, period_end), i.e. [prev-5th, this-5th).
--    Uncategorized rows are included; they must not disappear from totals.
SELECT COALESCE(SUM(t.base_amount_micro), 0) AS total_cny_micro
FROM   txn t
LEFT JOIN category c ON c.id = t.category_id
WHERE  t.direction = 'expense'
  AND  t.txn_date >= :window_start
  AND  t.txn_date <  :window_end
  AND  COALESCE(c.exclude_stats, 0) = 0;

-- 3) Fiscal-month credit-card amount converted to CNY micro-units.
--    The app performs Decimal arithmetic; this query only retrieves inputs.
SELECT fm.period_end,
       fm.credit_card_amount_minor,
       cur.minor_unit AS credit_card_minor_unit,
       rate.rate_to_base,
       rate.rate_date
FROM   fiscal_month fm
JOIN   currency cur ON cur.id = fm.credit_card_ccy_id
LEFT JOIN exchange_rate rate
       ON rate.currency_id = fm.credit_card_ccy_id
      AND rate.rate_date = (
          SELECT MAX(r2.rate_date)
          FROM   exchange_rate r2
          WHERE  r2.currency_id = fm.credit_card_ccy_id
            AND  r2.rate_date <= fm.period_end
      )
WHERE  fm.period_end = :period_end;

-- 4) Autocomplete: prefix match on prior content, most-used first.
--    :prefix is bound as escaped user input plus '%' by the app.
SELECT   content,
         COUNT(*) AS freq,
         MAX(txn_date) AS last_used
FROM     txn
WHERE    direction = :direction
  AND    content LIKE :prefix ESCAPE '\'
GROUP BY content
ORDER BY freq DESC, last_used DESC
LIMIT    8;

-- 5) Unsettled AA items, shown in original currency.
SELECT t.id,
       t.external_uid,
       t.txn_date,
       t.content,
       t.amount_minor,
       cur.code AS currency,
       cur.minor_unit,
       payer.name AS payer
FROM   txn t
JOIN   currency cur ON cur.id = t.currency_id
LEFT JOIN person payer ON payer.id = t.payer_id
WHERE  t.is_aa = 1
  AND  t.aa_settled = 0
ORDER BY t.txn_date, t.id;

-- 6) AA net balances for selected unsettled transactions in one currency.
--    The app expands :txn_ids as bound placeholders and runs this per currency.
WITH selected_txn AS (
    SELECT id, amount_minor, payer_id
    FROM   txn
    WHERE  is_aa = 1
      AND  aa_settled = 0
      AND  currency_id = :currency_id
      AND  id IN (:txn_id_1 /*, :txn_id_2, ... */)
),
paid AS (
    SELECT payer_id AS person_id,
           SUM(amount_minor) AS paid_minor
    FROM   selected_txn
    WHERE  payer_id IS NOT NULL
    GROUP BY payer_id
),
owed AS (
    SELECT tp.person_id,
           SUM(tp.owed_amount_minor) AS owed_minor
    FROM   txn_participant tp
    JOIN   selected_txn st ON st.id = tp.txn_id
    GROUP BY tp.person_id
)
SELECT p.id AS person_id,
       p.name,
       COALESCE(paid.paid_minor, 0) - COALESCE(owed.owed_minor, 0) AS net_minor
FROM   person p
LEFT JOIN paid ON paid.person_id = p.id
LEFT JOIN owed ON owed.person_id = p.id
WHERE  COALESCE(paid.paid_minor, 0) <> 0
    OR COALESCE(owed.owed_minor, 0) <> 0
ORDER BY net_minor DESC;

-- 7) Category breakdown for a half-open date range [start, end).
--    Uncategorized rows are grouped explicitly.
SELECT   COALESCE(c.id, 0) AS category_id,
         COALESCE(c.name, '未分类') AS category_name,
         c.color,
         COALESCE(SUM(t.base_amount_micro), 0) AS total_cny_micro,
         COUNT(*) AS n
FROM     txn t
LEFT JOIN category c ON c.id = t.category_id
WHERE    t.direction = 'expense'
  AND    t.txn_date >= :start
  AND    t.txn_date <  :end
  AND    (:include_uncategorized = 1 OR t.category_id IS NOT NULL)
  AND    (
             :category_filter_disabled = 1
          OR c.id IN (:category_id_1 /*, :category_id_2, ... */)
          OR (:include_uncategorized = 1 AND c.id IS NULL)
         )
GROUP BY COALESCE(c.id, 0), COALESCE(c.name, '未分类'), c.color
ORDER BY total_cny_micro DESC;

-- 8) Transaction lookup by xlsx sync identity.
SELECT id,
       external_uid,
       revision,
       last_xlsx_hash,
       last_synced_at,
       updated_at
FROM   txn
WHERE  external_uid = :external_uid;
