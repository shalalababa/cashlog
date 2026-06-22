"""Project paths and business constants.

Kept dependency-free so every other module can import it.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# backend/cashlog/config.py -> backend/ -> repo root
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

DOCS_DIR = REPO_ROOT / "docs"
SCHEMA_SQL = DOCS_DIR / "schema.sql"

# DB location can be overridden (CASHLOG_DB) for tests / separate profiles.
# JSON mirror and backups follow the DB so a temp DB never touches real data.
DB_PATH = Path(os.environ["CASHLOG_DB"]) if os.environ.get("CASHLOG_DB") \
    else BACKEND_DIR / "data" / "cashlog.db"
DATA_DIR = DB_PATH.parent
JSON_MIRROR_PATH = DB_PATH.with_suffix(".json")
REPORT_PATH = DATA_DIR / "migration_report.json"
BACKUP_DIR = DATA_DIR / "backups"

# The user's master workbook lives in the repo root.
WORKBOOK_PATH = REPO_ROOT / "记账单.xlsx"

# ---------------------------------------------------------------------------
# Business constants (see docs/PLAN.md)
# ---------------------------------------------------------------------------
BASE_CURRENCY = "CNY"          # 人民币 is the base for conversion
FISCAL_DAY = 5                 # fiscal month ends on the 5th
STALE_RATE_DAYS = 7            # a rate older than this (vs txn date) is flagged

# CNY conversion cache precision: CNY * 1_000_000 stored as INTEGER.
CNY_MICRO_SCALE = 1_000_000

# Reconciliation thresholds when comparing our import to the workbook's own
# 当日汇率 / 人民币换算 values.
RECONCILE_RMB_TOLERANCE = 0.01       # CNY
RECONCILE_RATE_TOLERANCE = 0.00005   # absolute rate units


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
