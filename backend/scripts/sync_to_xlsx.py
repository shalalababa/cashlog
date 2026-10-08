"""CLI: 同步到表格 (DB -> 记账单.xlsx). Backs up the workbook first.

Usage (from backend/):  python -m scripts.sync_to_xlsx [--force]

Refuses when the workbook holds edits that were never imported (run
sync_from_xlsx first); --force overwrites them anyway (a backup is kept).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import config, db  # noqa: E402
from cashlog import xlsxsync  # noqa: E402


def main() -> int:
    force = "--force" in sys.argv[1:]
    conn = db.connect()
    try:
        result = xlsxsync.export_to_xlsx(conn, force=force)
    except xlsxsync.PendingSheetChangesError as exc:
        print(f"❌ {exc}")
        print("   先运行 python -m scripts.sync_from_xlsx 预览/导入，或加 --force 覆盖（会先备份）。")
        return 3
    except xlsxsync.WorkbookLockedError as exc:
        print(f"❌ {exc}")
        print("   请关闭 Excel 中打开的 记账单.xlsx 后重试。")
        print("   （原文件未被修改，DB 数据也未受影响。）")
        return 2
    except PermissionError as exc:  # any other lock/permission issue
        print(f"❌ 写入失败：{exc}")
        print("   文件可能被占用或无写入权限。原文件与 DB 数据均未受影响。")
        return 2
    finally:
        conn.close()
    print(f"Wrote {config.WORKBOOK_PATH}")
    print(f"  expense rows: {result['written']['expense']}")
    print(f"  income rows : {result['written']['income']}")
    print(f"  synced_at   : {result['synced_at']}")
    print(f"  backups in  : {config.BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
