"""CLI: build the SQLite DB from the workbook and print the migration summary.

Usage (from backend/):
    python -m scripts.migrate
    python scripts/migrate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (python scripts/migrate.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import config, pipeline  # noqa: E402


def main() -> int:
    print(f"Workbook : {config.WORKBOOK_PATH}")
    print(f"Database : {config.DB_PATH}")
    report = pipeline.run(reset=True)
    s = report["_summary"]

    print("\n=== Migration summary ===")
    for key, value in s.items():
        print(f"  {key:18}: {value}")

    print(f"\nJSON mirror : {config.JSON_MIRROR_PATH}")
    print(f"Full report : {config.REPORT_PATH}")

    if report["anomalies"]:
        print("\n--- Anomalies (NOT imported) ---")
        for a in report["anomalies"]:
            print(f"  {a['sheet']} R{a['row']}: {', '.join(a['reasons'])}  raw={a['raw']}")
    if report["reconcile_diffs"]:
        print(f"\n--- Reconciliation diffs ({len(report['reconcile_diffs'])}) ---")
        for d in report["reconcile_diffs"][:20]:
            print(f"  {d['sheet']} R{d['row']}: rate {d['our_rate']} vs {d['wb_rate']} "
                  f"(d={d['rate_diff']}), cny {d['our_cny']} vs {d['wb_cny']} (d={d['rmb_diff']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
