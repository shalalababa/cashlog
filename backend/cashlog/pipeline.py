"""End-to-end P1 pipeline: init DB -> seed -> import workbook -> JSON mirror.

Writes a human-readable migration report to data/migration_report.json and
returns the Report object.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from . import config, db, importer, jsonsync, seed


def run(workbook_path: Optional[Path] = None, *, reset: bool = True) -> dict:
    config.ensure_data_dirs()
    db.init_db(reset=reset)
    conn = db.connect()
    try:
        seed.seed(conn)
        report = importer.import_workbook(conn, workbook_path)
        jsonsync.export_json(conn)
    finally:
        conn.close()

    report_dict = asdict(report)
    report_dict["_summary"] = report.summary()
    config.REPORT_PATH.write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_dict
