-- Cashlog local SQLite schema.
-- SQLite is the source of truth; xlsx and JSON are sync targets.
-- App code owns writes and must use parameterized statements.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------
CREATE TABLE currency (
    id          INTEGER PRIMARY KEY,
    code        TEXT    NOT NULL UNIQUE,          -- 'USD', 'CNY', 'JPY', 'HKD'
    name        TEXT    NOT NULL,                 -- '美元'
    symbol      TEXT,
    minor_unit  INTEGER NOT NULL DEFAULT 2 CHECK (minor_unit >= 0 AND minor_unit <= 6),
    is_base     INTEGER NOT NULL DEFAULT 0 CHECK (is_base IN (0,1)),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE UNIQUE INDEX idx_currency_single_base ON currency (is_base) WHERE is_base = 1;

CREATE TABLE exchange_rate (
    id            INTEGER PRIMARY KEY,
    currency_id   INTEGER NOT NULL REFERENCES currency(id) ON DELETE CASCADE,
    rate_date     TEXT    NOT NULL,               -- ISO 'YYYY-MM-DD'
    rate_to_base  TEXT    NOT NULL,               -- decimal string, CNY per 1 unit
    source        TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (currency_id, rate_date),
    CHECK (CAST(rate_to_base AS REAL) > 0)
);
-- Drives "most recent rate on-or-before date" lookup.
CREATE INDEX idx_rate_lookup ON exchange_rate (currency_id, rate_date DESC);

CREATE TABLE category (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN ('expense','income')),
    color          TEXT,
    icon           TEXT,
    exclude_stats  INTEGER NOT NULL DEFAULT 0 CHECK (exclude_stats IN (0,1)),
    sort_order     INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    UNIQUE (name, kind)
);

CREATE TABLE person (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL UNIQUE,
    initial  TEXT,
    is_self  INTEGER NOT NULL DEFAULT 0 CHECK (is_self IN (0,1)),
    active   INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE UNIQUE INDEX idx_person_single_self ON person (is_self) WHERE is_self = 1;

-- ---------------------------------------------------------------------------
-- Transactions (merged 支出 + 入账)
-- ---------------------------------------------------------------------------
CREATE TABLE txn (
    id                   INTEGER PRIMARY KEY,
    external_uid         TEXT    NOT NULL UNIQUE, -- stable id written to xlsx/JSON
    txn_date             TEXT    NOT NULL,        -- 'YYYY-MM-DD'
    direction            TEXT    NOT NULL CHECK (direction IN ('expense','income')),
    amount_minor         INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency_id          INTEGER NOT NULL REFERENCES currency(id),
    content              TEXT    NOT NULL DEFAULT '',
    category_id          INTEGER REFERENCES category(id),
    note                 TEXT,

    -- AA tracking. AA uses the original currency, never CNY conversion.
    is_aa                INTEGER NOT NULL DEFAULT 0 CHECK (is_aa IN (0,1)),
    payer_id             INTEGER REFERENCES person(id),
    aa_settled           INTEGER NOT NULL DEFAULT 0 CHECK (aa_settled IN (0,1)),

    -- Cached conversion. App recomputes these when amount/date/currency/rate changes.
    rate_used            TEXT,                    -- decimal string from exchange_rate.rate_to_base
    rate_date_used       TEXT,
    base_amount_micro    INTEGER,                 -- CNY * 1,000,000
    rate_stale_days      INTEGER NOT NULL DEFAULT 0 CHECK (rate_stale_days >= 0),

    -- Sync metadata.
    revision             INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    last_xlsx_hash       TEXT,
    last_synced_at       TEXT,
    source_sheet         TEXT,
    source_row           INTEGER,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_txn_date         ON txn (txn_date);
CREATE INDEX idx_txn_dir_date     ON txn (direction, txn_date);
CREATE INDEX idx_txn_dir_content  ON txn (direction, content);
CREATE INDEX idx_txn_cat          ON txn (category_id);
CREATE INDEX idx_txn_currency     ON txn (currency_id, txn_date);
CREATE INDEX idx_txn_aa           ON txn (is_aa, aa_settled);

CREATE TRIGGER trg_txn_category_kind_insert
BEFORE INSERT ON txn
WHEN NEW.category_id IS NOT NULL
     AND EXISTS (
         SELECT 1
         FROM category c
         WHERE c.id = NEW.category_id
           AND c.kind <> NEW.direction
     )
BEGIN
    SELECT RAISE(ABORT, 'category.kind must match txn.direction');
END;

CREATE TRIGGER trg_txn_category_kind_update
BEFORE UPDATE OF direction, category_id ON txn
WHEN NEW.category_id IS NOT NULL
     AND EXISTS (
         SELECT 1
         FROM category c
         WHERE c.id = NEW.category_id
           AND c.kind <> NEW.direction
     )
BEGIN
    SELECT RAISE(ABORT, 'category.kind must match txn.direction');
END;

-- AA participants per transaction. owed_amount_minor is the auditable result.
-- weight/fixed_amount_minor describe how that result was derived.
CREATE TABLE txn_participant (
    txn_id              INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
    person_id           INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    weight              TEXT,                     -- decimal string; NULL means equal share
    fixed_amount_minor  INTEGER CHECK (fixed_amount_minor IS NULL OR fixed_amount_minor >= 0),
    owed_amount_minor   INTEGER NOT NULL CHECK (owed_amount_minor >= 0),
    PRIMARY KEY (txn_id, person_id),
    CHECK (weight IS NULL OR CAST(weight AS REAL) > 0)
);
CREATE INDEX idx_txn_participant_person ON txn_participant (person_id);

-- ---------------------------------------------------------------------------
-- Fiscal months (manual credit-card figure; everything else is derived)
-- ---------------------------------------------------------------------------
CREATE TABLE fiscal_month (
    id                         INTEGER PRIMARY KEY,
    period_end                 TEXT    NOT NULL UNIQUE, -- the 5th, 'YYYY-MM-05'
    credit_card_amount_minor   INTEGER NOT NULL DEFAULT 0 CHECK (credit_card_amount_minor >= 0),
    credit_card_ccy_id         INTEGER REFERENCES currency(id),
    note                       TEXT,
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- AA / receipt calculator (supersedes Amazon calculator)
-- ---------------------------------------------------------------------------
CREATE TABLE aa_session (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT,
    total_with_tax_minor  INTEGER NOT NULL CHECK (total_with_tax_minor >= 0),
    tax_amount_minor      INTEGER NOT NULL DEFAULT 0 CHECK (tax_amount_minor >= 0),
    currency_id           INTEGER NOT NULL REFERENCES currency(id),
    payer_id              INTEGER REFERENCES person(id),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE aa_session_item (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES aa_session(id) ON DELETE CASCADE,
    label          TEXT,
    pretax_minor   INTEGER NOT NULL CHECK (pretax_minor >= 0),
    sort_order     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_aa_session_item_session ON aa_session_item (session_id, sort_order);

CREATE TABLE aa_session_item_share (
    item_id    INTEGER NOT NULL REFERENCES aa_session_item(id) ON DELETE CASCADE,
    person_id  INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    weight     TEXT,                                -- NULL means equal share
    PRIMARY KEY (item_id, person_id),
    CHECK (weight IS NULL OR CAST(weight AS REAL) > 0)
);

CREATE TABLE setting (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
