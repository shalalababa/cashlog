"""Two-way xlsx sync (P2).

  export_to_xlsx  —  "同步到表格": DB -> xlsx. Rewrites the 支出/入账 data sheets
                     from the DB (source of truth), writes a hidden _cashlog_uid
                     column, rebuilds 汇率/统计 so the workbook stays usable on
                     its own, backs up the workbook, saves atomically, then marks
                     the synced baseline on each txn. Calculator sheets are
                     preserved untouched.

  diff_from_xlsx  —  "从表格同步" preview: xlsx -> proposed changes. Matches rows
                     by _cashlog_uid (so row reorder is a no-op) and by content
                     hash (so unchanged rows are skipped). Classifies each row as
                     new / modified / conflict / unknown_uid / anomaly. A DB row
                     missing from the sheet is a deletion only if it was synced
                     before (last_synced_at set); an app-created row not yet
                     exported goes to db_only, never deleted. Applies nothing.

  apply_diff      —  Applies new + modified (deletions/conflicts are opt-in).

Identity & conflict model (per txn):
  last_xlsx_hash = content hash at the last successful sync (baseline).
  db_changed     = current DB hash   != baseline
  xlsx_changed   = incoming xlsx hash != baseline
  conflict       = both changed AND they disagree -> never auto-overwritten.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import openpyxl

from . import config, importer, jsonsync, money, rates

# direction -> sheet name + the workbook's column-D header
DATA_SHEETS = {
    "expense": ("支出", "消费内容"),
    "income": ("入账", "入账来源"),
}
UID_COL = 8  # column H
UID_HEADER = "_cashlog_uid"
DATE_FMT = "yyyy-mm-dd"
RATE_SHEET = "汇率"
STATS_SHEET = "统计"


class WorkbookLockedError(RuntimeError):
    """Raised when the target xlsx cannot be replaced (typically open in Excel)."""

    def __init__(self, path):
        super().__init__(
            f"无法写入 {path}：文件可能正被 Excel 打开。请关闭后重试。"
        )
        self.path = path


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def _header(content_header: str) -> list:
    return ["日期", "金额", "币种", content_header, "分类",
            "人民币换算", "当日汇率", UID_HEADER]


def _db_hash(direction: str, txn_date: str, amount_minor: int, code: str,
             content: str, cat_name: Optional[str], note: Optional[str]) -> str:
    return importer._row_hash(direction, txn_date, amount_minor, code,
                              content or "", cat_name or "", note or "")


def _fetch_txns(conn: sqlite3.Connection, direction: str) -> list:
    return conn.execute(
        """SELECT t.id, t.external_uid, t.txn_date, t.amount_minor, t.content,
                  t.note, t.rate_used, t.last_xlsx_hash, t.last_synced_at, t.revision,
                  cur.code AS code, cur.name AS ccy_name, cur.minor_unit,
                  c.name AS cat_name
           FROM   txn t
           JOIN   currency cur ON cur.id = t.currency_id
           LEFT   JOIN category c ON c.id = t.category_id
           WHERE  t.direction = ?
           ORDER  BY t.txn_date, t.id""",
        (direction,),
    ).fetchall()


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _clear_trailing(ws, first_row: int, last_row: int, ncols: int) -> None:
    for rr in range(first_row, last_row + 1):
        for col in range(1, ncols + 1):
            ws.cell(row=rr, column=col).value = None


def _rebuild_rates_sheet(conn: sqlite3.Connection, wb) -> None:
    """汇率: 日期 / 币种 / 当日汇率, rebuilt from exchange_rate (values)."""
    ws = wb[RATE_SHEET] if RATE_SHEET in wb.sheetnames else wb.create_sheet(RATE_SHEET)
    original_max = ws.max_row
    for col, h in enumerate(["日期", "币种", "当日汇率"], start=1):
        ws.cell(row=1, column=col, value=h)
    r = 2
    for row in conn.execute(
        """SELECT er.rate_date, cur.name AS ccy, er.rate_to_base
           FROM exchange_rate er JOIN currency cur ON cur.id = er.currency_id
           ORDER BY er.rate_date, cur.code"""):
        ws.cell(row=r, column=1, value=date.fromisoformat(row["rate_date"])).number_format = DATE_FMT
        ws.cell(row=r, column=2, value=row["ccy"])
        ws.cell(row=r, column=3, value=float(row["rate_to_base"]))
        r += 1
    _clear_trailing(ws, r, original_max, 3)


def _rebuild_stats_sheet(conn: sqlite3.Connection, wb, base_id: int,
                         usd_id: Optional[int]) -> None:
    """统计: rebuilt from fiscal_month. Derived columns use the same formulas as
    the original workbook (so the file stays standalone-usable); 当日汇率 and the
    manual 信用卡金额 are written as values. The 学费/特殊 exclusion list is taken
    live from the DB so the SUMIFS stays correct if categories change."""
    excl = [row["name"] for row in conn.execute(
        "SELECT name FROM category WHERE kind='expense' AND exclude_stats=1 ORDER BY name")]
    excl_terms = "".join(f', 支出!$E:$E, "<>{name}"' for name in excl)

    ws = wb[STATS_SHEET] if STATS_SHEET in wb.sheetnames else wb.create_sheet(STATS_SHEET)
    original_max = ws.max_row
    headers = ["财政月", "总支出金额", "币种", "美元换算", "信用卡金额",
               "币种", "人民币换算", "当日汇率", "占总支出"]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)

    r = 2
    for fm in conn.execute("SELECT * FROM fiscal_month ORDER BY period_end"):
        pe = fm["period_end"]
        rl = rates.lookup(conn, usd_id, pe, base_currency_id=base_id) if usd_id else None
        usd_rate = float(rl.rate_to_base) if rl else None
        cc_major = float(money.from_minor(fm["credit_card_amount_minor"], 2))
        ws.cell(row=r, column=1, value=date.fromisoformat(pe)).number_format = DATE_FMT
        ws.cell(row=r, column=2,
                value=f'=SUMIFS(支出!$F:$F, 支出!$A:$A,">="&EDATE($A{r},-1), '
                      f'支出!$A:$A,"<"&$A{r}{excl_terms})')
        ws.cell(row=r, column=3, value="人民币")
        ws.cell(row=r, column=4, value=f"=B{r}/H{r}")
        ws.cell(row=r, column=5, value=cc_major)
        ws.cell(row=r, column=6, value="美元")
        ws.cell(row=r, column=7, value=f"=E{r}*H{r}")
        ws.cell(row=r, column=8, value=usd_rate)
        ws.cell(row=r, column=9, value=f"=G{r}/B{r}")
        r += 1
    _clear_trailing(ws, r, original_max, 9)


# ---------------------------------------------------------------------------
# Export: DB -> xlsx
# ---------------------------------------------------------------------------
def export_to_xlsx(conn: sqlite3.Connection, target: Optional[Path] = None, *,
                   template: Optional[Path] = None, backup: bool = True,
                   backup_dir: Optional[Path] = None, write_json: bool = True) -> dict:
    target = Path(target) if target else config.WORKBOOK_PATH
    load_from = Path(template) if template else (target if target.exists() else None)

    if load_from and load_from.exists():
        wb = openpyxl.load_workbook(str(load_from))  # keep formulas/other sheets
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

    pending: list = []  # (txn_id, db_hash) to mark as synced AFTER a clean write
    written = {"expense": 0, "income": 0}

    for direction, (sheet_name, content_header) in DATA_SHEETS.items():
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
        original_max = ws.max_row

        for col, value in enumerate(_header(content_header), start=1):
            ws.cell(row=1, column=col, value=value)

        r = 2
        for t in _fetch_txns(conn, direction):
            major = money.from_minor(t["amount_minor"], t["minor_unit"])
            ws.cell(row=r, column=1, value=date.fromisoformat(t["txn_date"])).number_format = DATE_FMT
            ws.cell(row=r, column=2, value=float(major))
            ws.cell(row=r, column=3, value=t["ccy_name"])
            ws.cell(row=r, column=4, value=t["content"])
            ws.cell(row=r, column=5, value=t["cat_name"] or "")
            ws.cell(row=r, column=6, value=f"=B{r}*G{r}")
            ws.cell(row=r, column=7, value=float(t["rate_used"]) if t["rate_used"] is not None else None)
            ws.cell(row=r, column=UID_COL, value=t["external_uid"])
            pending.append((t["id"], _db_hash(direction, t["txn_date"], t["amount_minor"],
                                              t["code"], t["content"], t["cat_name"], t["note"])))
            r += 1
            written[direction] += 1

        # NB: ws.cell(..., value=None) is a no-op in openpyxl; _clear_trailing
        # assigns .value on the cell object to actually clear it.
        _clear_trailing(ws, r, original_max, UID_COL)

        ws.column_dimensions[openpyxl.utils.get_column_letter(UID_COL)].hidden = True

    base_id = rates.get_base_currency_id(conn)
    usd = conn.execute("SELECT id FROM currency WHERE code='USD'").fetchone()
    _rebuild_rates_sheet(conn, wb)
    _rebuild_stats_sheet(conn, wb, base_id, usd["id"] if usd else None)

    # --- Backup, then atomic save. DB is only marked synced on success. ---
    if backup and target.exists():
        bdir = Path(backup_dir) if backup_dir else config.BACKUP_DIR
        bdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target, bdir / f"{target.stem}_{ts}{target.suffix}")

    tmp = target.with_name(target.name + ".tmp")
    try:
        wb.save(str(tmp))
        os.replace(str(tmp), str(target))
    except PermissionError as exc:
        _safe_unlink(tmp)
        raise WorkbookLockedError(target) from exc
    except Exception:
        _safe_unlink(tmp)
        raise

    now = _now()
    for txn_id, h in pending:
        conn.execute(
            "UPDATE txn SET last_xlsx_hash = ?, last_synced_at = ? WHERE id = ?",
            (h, now, txn_id),
        )
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)

    return {"target": str(target), "written": written, "synced_at": now}


# ---------------------------------------------------------------------------
# Diff: xlsx -> proposed changes (no writes)
# ---------------------------------------------------------------------------
@dataclass
class SyncDiff:
    new: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    deleted: list = field(default_factory=list)
    conflict: list = field(default_factory=list)
    unknown_uid: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)
    db_only: list = field(default_factory=list)   # in DB, never synced to xlsx yet
    unchanged: int = 0

    def summary(self) -> dict:
        return {
            "new": len(self.new), "modified": len(self.modified),
            "deleted": len(self.deleted), "conflict": len(self.conflict),
            "unknown_uid": len(self.unknown_uid), "anomalies": len(self.anomalies),
            "db_only": len(self.db_only), "unchanged": self.unchanged,
        }


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def diff_from_xlsx(conn: sqlite3.Connection, source: Optional[Path] = None) -> SyncDiff:
    source = Path(source) if source else config.WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(source), data_only=True)
    diff = SyncDiff()

    ccy = importer.currency_id_map(conn)
    cat_map = {(row["name"], row["kind"]): row["id"]
               for row in conn.execute("SELECT id, name, kind FROM category")}

    # DB snapshot keyed by uid, with current hash + synced baseline.
    db_by_uid: dict = {}
    in_scope_uids = {"expense": set(), "income": set()}
    for direction in DATA_SHEETS:
        for t in _fetch_txns(conn, direction):
            cur_hash = _db_hash(direction, t["txn_date"], t["amount_minor"], t["code"],
                                t["content"], t["cat_name"], t["note"])
            db_by_uid[t["external_uid"]] = {
                "id": t["id"], "direction": direction, "current_hash": cur_hash,
                "baseline": t["last_xlsx_hash"], "content": t["content"],
                "synced": t["last_synced_at"] is not None,
            }
            in_scope_uids[direction].add(t["external_uid"])

    seen: set = set()
    try:
        for direction, (sheet_name, _) in DATA_SHEETS.items():
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            for r in range(2, ws.max_row + 1):
                cells = [ws.cell(row=r, column=c).value for c in range(1, 6)]
                uid = ws.cell(row=r, column=UID_COL).value
                if all(c in (None, "") for c in cells) and not uid:
                    continue

                iso = _iso(cells[0])
                amount_dec = money.parse_decimal(cells[1])
                ccy_row = ccy.get(cells[2]) if cells[2] is not None else None
                problems = []
                if iso is None:
                    problems.append("missing/invalid date")
                if amount_dec is None:
                    problems.append(f"unparseable amount: {cells[1]!r}")
                if ccy_row is None:
                    problems.append(f"unknown/missing currency: {cells[2]!r}")
                if problems:
                    diff.anomalies.append({"sheet": sheet_name, "row": r,
                                           "reasons": problems, "uid": uid})
                    continue

                content = "" if cells[3] is None else str(cells[3]).strip()
                cat_name = None if cells[4] in (None, "") else str(cells[4]).strip()
                amount_minor = money.to_minor(amount_dec, ccy_row["minor_unit"])
                xlsx_hash = _db_hash(direction, iso, amount_minor, ccy_row["code"],
                                     content, cat_name, "")
                payload = {"sheet": sheet_name, "row": r, "uid": uid, "direction": direction,
                           "txn_date": iso, "amount_minor": amount_minor,
                           "currency_id": ccy_row["id"], "content": content,
                           "category_id": cat_map.get((cat_name, direction)) if cat_name else None,
                           "xlsx_hash": xlsx_hash}

                if not uid:
                    diff.new.append(payload)
                    continue

                seen.add(uid)
                rec = db_by_uid.get(uid)
                if rec is None:
                    diff.unknown_uid.append({"sheet": sheet_name, "row": r, "uid": uid})
                    continue

                xlsx_changed = xlsx_hash != rec["baseline"]
                db_changed = rec["current_hash"] != rec["baseline"]
                if not xlsx_changed:
                    diff.unchanged += 1
                elif db_changed and xlsx_hash != rec["current_hash"]:
                    diff.conflict.append({**payload, "txn_id": rec["id"],
                                          "db_content": rec["content"]})
                else:
                    diff.modified.append({**payload, "txn_id": rec["id"]})

        for direction in DATA_SHEETS:
            for uid in in_scope_uids[direction] - seen:
                rec = db_by_uid[uid]
                entry = {"uid": uid, "txn_id": rec["id"],
                         "direction": direction, "content": rec["content"]}
                # Only rows that were previously written to the workbook can be a
                # deletion. A row created in the app but not yet "同步到表格" is
                # simply unsynced — never a delete candidate.
                if rec["synced"]:
                    diff.deleted.append(entry)
                else:
                    diff.db_only.append(entry)
    finally:
        wb.close()
    return diff


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def _convert(conn, currency_id: int, txn_date: str, amount_minor: int, base_id: int):
    cur = conn.execute("SELECT minor_unit FROM currency WHERE id = ?", (currency_id,)).fetchone()
    rl = rates.lookup(conn, currency_id, txn_date, base_currency_id=base_id)
    if rl is None:
        return None, None, 0, None
    base_micro = money.to_base_micro(amount_minor, cur["minor_unit"], rl.rate_to_base)
    return rl.rate_to_base, rl.rate_date, rl.stale_days, base_micro


def apply_diff(conn: sqlite3.Connection, source: Optional[Path], diff: SyncDiff, *,
               apply_deletions: bool = False, apply_conflicts: bool = False,
               write_json: bool = True) -> dict:
    base_id = rates.get_base_currency_id(conn)
    now = _now()
    applied = {"new": 0, "modified": 0, "deleted": 0, "conflict": 0}

    def upsert_values(p):
        rate_used, rate_date, stale, base_micro = _convert(
            conn, p["currency_id"], p["txn_date"], p["amount_minor"], base_id)
        return rate_used, rate_date, stale, base_micro

    for p in diff.new:
        rate_used, rate_date, stale, base_micro = upsert_values(p)
        uid = importer.make_external_uid(p["sheet"], p["row"], p["xlsx_hash"])
        conn.execute(
            """INSERT INTO txn (external_uid, txn_date, direction, amount_minor,
                   currency_id, content, category_id, is_aa, aa_settled,
                   rate_used, rate_date_used, base_amount_micro, rate_stale_days,
                   revision, last_xlsx_hash, last_synced_at, source_sheet, source_row)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (uid, p["txn_date"], p["direction"], p["amount_minor"], p["currency_id"],
             p["content"], p["category_id"], rate_used, rate_date, base_micro, stale,
             p["xlsx_hash"], now, p["sheet"], p["row"]))
        applied["new"] += 1

    targets = list(diff.modified) + (list(diff.conflict) if apply_conflicts else [])
    for p in targets:
        rate_used, rate_date, stale, base_micro = upsert_values(p)
        conn.execute(
            """UPDATE txn SET txn_date=?, amount_minor=?, currency_id=?, content=?,
                   category_id=?, rate_used=?, rate_date_used=?, base_amount_micro=?,
                   rate_stale_days=?, revision=revision+1, last_xlsx_hash=?, last_synced_at=?
               WHERE id=?""",
            (p["txn_date"], p["amount_minor"], p["currency_id"], p["content"],
             p["category_id"], rate_used, rate_date, base_micro, stale,
             p["xlsx_hash"], now, p["txn_id"]))
        applied["conflict" if p in diff.conflict else "modified"] += 1

    if apply_deletions:
        for d in diff.deleted:
            conn.execute("DELETE FROM txn WHERE id = ?", (d["txn_id"],))
            applied["deleted"] += 1

    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return applied
