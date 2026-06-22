"""CLI: 从表格同步 (记账单.xlsx -> DB). Previews a diff; applies only with --apply.

Usage (from backend/):
    python -m scripts.sync_from_xlsx            # preview only
    python -m scripts.sync_from_xlsx --apply    # apply new + modified
    python -m scripts.sync_from_xlsx --apply --deletions  # also apply deletions
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import db, xlsxsync  # noqa: E402


def main(argv: list) -> int:
    apply = "--apply" in argv
    deletions = "--deletions" in argv

    conn = db.connect()
    try:
        diff = xlsxsync.diff_from_xlsx(conn)
        print("=== 从表格同步 diff 预览 ===")
        for key, value in diff.summary().items():
            print(f"  {key:12}: {value}")

        for label, items in (("conflict", diff.conflict), ("modified", diff.modified),
                             ("new", diff.new), ("deleted", diff.deleted),
                             ("anomalies", diff.anomalies)):
            for it in items[:10]:
                where = f"{it.get('sheet','?')} R{it.get('row','?')}"
                print(f"  [{label}] {where} {it.get('content', it.get('uid',''))}")

        if diff.conflict:
            print("\n⚠ 存在冲突，不会自动覆盖。请先在表格或应用中解决。")

        if apply:
            applied = xlsxsync.apply_diff(conn, None, diff, apply_deletions=deletions)
            print(f"\nApplied: {applied}")
        else:
            print("\n(预览模式；加 --apply 写入 DB)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
