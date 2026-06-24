"""Project paths and business constants.

Kept dependency-free so every other module can import it.

Two runtime shapes are supported:

* **Source / dev** (``python -m scripts.serve``): paths derive from this file's
  location in the repo — exactly as before.
* **Frozen sidecar** (PyInstaller, used by the Tauri desktop build): ``__file__``
  points inside a temporary extraction dir, so read-only assets (schema.sql,
  migrations) are read from the bundle (``sys._MEIPASS``) and *writable* data
  (DB / JSON / xlsx / backups) lives in a stable per-user directory instead.

In both shapes ``CASHLOG_DB`` still overrides the database location (tests,
separate profiles), and the JSON mirror + backups always follow the DB so a
throwaway DB never touches real data. The desktop build can additionally point
at an existing ledger with ``CASHLOG_DATA_DIR`` / ``CASHLOG_WORKBOOK``.
"""
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FROZEN = getattr(sys, "frozen", False)


def _bundle_dir() -> Path:
    """Directory holding bundled read-only assets when frozen.

    PyInstaller onefile extracts to ``sys._MEIPASS``; onedir keeps them next to
    the executable.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(sys.executable).resolve().parent


def _frozen_data_dir() -> Path:
    """Stable, writable per-user data directory for the desktop build."""
    env = os.environ.get("CASHLOG_DATA_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Cashlog"
    return Path.home() / ".cashlog"


if FROZEN:
    # Read-only assets bundled into the sidecar (see the PyInstaller spec, which
    # adds docs/schema.sql and docs/migrations under a "docs" subdir).
    DOCS_DIR = _bundle_dir() / "docs"
    BACKEND_DIR = _bundle_dir()      # not meaningful when frozen; kept for parity
    REPO_ROOT = _bundle_dir()
else:
    # backend/cashlog/config.py -> backend/ -> repo root
    BACKEND_DIR = Path(__file__).resolve().parent.parent
    REPO_ROOT = BACKEND_DIR.parent
    DOCS_DIR = REPO_ROOT / "docs"

SCHEMA_SQL = DOCS_DIR / "schema.sql"
# Additive, idempotent migrations applied on top of the schema.sql baseline
# (e.g. tables added in later phases). Applied by db.ensure_schema.
MIGRATIONS_DIR = DOCS_DIR / "migrations"

# Built single-page frontend. When present it is mounted at "/" so the API and
# UI share one origin (no CORS, relative `/api/...` calls just work). In a source
# checkout this is produced by `npm run build`; the frozen desktop sidecar bundles
# it (see the PyInstaller spec) and serves it — that *is* the desktop UI, so the
# webview can point straight at the backend. REPO_ROOT == the bundle dir when
# frozen, so this resolves correctly in both shapes.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

# DB location can be overridden (CASHLOG_DB) for tests / separate profiles.
# JSON mirror and backups follow the DB so a temp DB never touches real data.
if os.environ.get("CASHLOG_DB"):
    DB_PATH = Path(os.environ["CASHLOG_DB"])
elif FROZEN:
    DB_PATH = _frozen_data_dir() / "cashlog.db"
else:
    DB_PATH = BACKEND_DIR / "data" / "cashlog.db"
DATA_DIR = DB_PATH.parent
JSON_MIRROR_PATH = DB_PATH.with_suffix(".json")
REPORT_PATH = DATA_DIR / "migration_report.json"
BACKUP_DIR = DATA_DIR / "backups"

# The user's master workbook. In the repo it sits at the root next to the
# sources; the desktop build keeps it alongside the data dir (overridable).
if FROZEN:
    WORKBOOK_PATH = Path(os.environ.get("CASHLOG_WORKBOOK") or (DATA_DIR / "记账单.xlsx"))
else:
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
