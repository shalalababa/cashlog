# Cashlog

A local-first personal finance app that replaced a hand-maintained Excel ledger. SQLite is the
single source of truth; a JSON mirror is written automatically, and the original `.xlsx` workbook
stays in sync through explicit two-way sync with a diff preview. The UI is in Chinese.
[中文说明](README.zh-CN.md) · [Design plan (Chinese)](docs/PLAN.md)

## Features

- **Transactions**: multi-currency expenses and income (amounts stored as integer minor units),
  historical daily exchange rates (nearest rate on or before the transaction date), and
  prefix autocomplete that fills in the category.
- **Shared expenses (AA)**: participants, structured splits, a receipt calculator that splits
  shared items and allocates tax pro rata, and settle-up with a minimal set of transfers.
- **Statistics**: fiscal-month totals, category donut and treemap charts, and spending and
  category-share trends (ECharts).
- **Budgets and dashboard**: overall and per-category budgets (absolute or percentage of total),
  month-over-month overview, and reminders for unsettled shared expenses.
- **Excel sync**: DB → workbook (with an automatic backup before every write) and workbook → DB
  (read-only diff preview, then `--apply`).
- **Desktop build**: a Tauri v2 shell around the same backend, packaged as a single-file
  PyInstaller sidecar, so the installed app needs no system Python.

## Stack

- Backend: Python, FastAPI, SQLite, openpyxl (`backend/`)
- Frontend: React, TypeScript, Vite, ECharts (`frontend/`)
- Desktop: Tauri v2 + PyInstaller sidecar (`frontend/src-tauri/`, [docs/DESKTOP.md](docs/DESKTOP.md))
- Schema and migrations: [docs/schema.sql](docs/schema.sql), [docs/migrations/](docs/migrations/)

## Getting started

```bash
cd backend && pip install -r requirements.txt
python -m scripts.migrate          # build the DB from an existing workbook, if you have one
cd ../frontend && npm install
```

Run the backend (http://127.0.0.1:8000) and the dev server (http://localhost:5173, proxies `/api`):

```bash
cd backend && python -m scripts.serve
cd frontend && npm run dev
```

Or build the frontend once and let the backend serve it from the same origin:

```bash
cd frontend && npm run build
cd ../backend && python -m scripts.serve
```

## Excel sync

```bash
cd backend
python -m scripts.sync_to_xlsx              # DB -> workbook, backs up first
python -m scripts.sync_from_xlsx            # workbook -> DB, preview the diff only
python -m scripts.sync_from_xlsx --apply    # apply additions and edits
```

## Configuration

`CASHLOG_DB`, `CASHLOG_DATA_DIR` and `CASHLOG_WORKBOOK` override the database, data directory and
workbook paths, which is useful for tests or separate ledgers. No personal data ships with the
repository; the database and workbook live in ignored local paths.

## Tests

```bash
cd backend && python -m pytest tests -q
```

## Desktop build

```bash
cd backend && python scripts/build_sidecar.py   # build the frontend and the backend sidecar
cd frontend && npm run tauri build              # produce MSI/NSIS installers (needs Rust)
```
