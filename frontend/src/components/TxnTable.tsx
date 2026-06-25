import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { motion } from "framer-motion";
import type { Txn } from "../types";

interface Props {
  rows: Txn[];
  total: number;
  offset: number;
  limit: number;
  sort: string;
  order: string;
  loading: boolean;
  onSort: (col: string) => void;
  onPage: (offset: number) => void;
  onEdit: (t: Txn) => void;
  onDelete: (t: Txn) => void;
}

const SORTABLE = new Set(["date", "amount", "base_cny", "content", "category"]);

export default function TxnTable(props: Props) {
  const { rows, total, offset, limit, sort, order, onSort, onPage, onEdit, onDelete } = props;
  const [visibility, setVisibility] = useState<VisibilityState>({});
  const [menuOpen, setMenuOpen] = useState(false);

  const columns = useMemo<ColumnDef<Txn>[]>(
    () => [
      {
        id: "date",
        header: "日期",
        accessorKey: "date",
        cell: (c) => <span className="muted">{c.getValue<string>()}</span>,
      },
      {
        id: "direction",
        header: "方向",
        cell: (c) => {
          const d = c.row.original.direction;
          return <span className={`badge dir-${d}`}>{d === "expense" ? "支出" : "入账"}</span>;
        },
      },
      {
        id: "content",
        header: "内容",
        accessorKey: "content",
        cell: (c) => {
          const t = c.row.original;
          return (
            <span>
              {t.content || <span className="muted">—</span>}
              {t.is_aa && <span className="badge aa" style={{ marginLeft: 6 }}>AA{t.aa_settled ? "✓" : ""}</span>}
              {t.legacy_aa && <span className="badge aa" style={{ marginLeft: 6 }}>AA候选</span>}
            </span>
          );
        },
      },
      {
        id: "category",
        header: "分类",
        cell: (c) => {
          const t = c.row.original;
          if (!t.category) return <span className="badge uncat">未分类</span>;
          return (
            <span className="chip">
              <span className="swatch" style={{ background: t.category_color ?? "#ccc" }} />
              {t.category}
            </span>
          );
        },
      },
      {
        id: "amount",
        header: () => <div className="num">金额</div>,
        cell: (c) => {
          const t = c.row.original;
          return (
            <div className={`num amount ${t.direction}`}>
              {t.direction === "expense" ? "-" : "+"}
              {t.amount} {t.currency}
            </div>
          );
        },
      },
      {
        id: "base_cny",
        header: () => <div className="num">人民币</div>,
        cell: (c) => {
          const t = c.row.original;
          return (
            <div className="num">
              {t.base_cny ? `¥${t.base_cny}` : <span className="muted">—</span>}
              {t.rate_stale && <span className="badge stale" style={{ marginLeft: 6 }}>旧汇率</span>}
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: (c) => (
          <div className="row-actions">
            <button className="btn sm ghost" onClick={() => onEdit(c.row.original)}>编辑</button>
            <button className="btn sm ghost danger" onClick={() => onDelete(c.row.original)}>删除</button>
          </div>
        ),
      },
    ],
    [onEdit, onDelete]
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { columnVisibility: visibility },
    onColumnVisibilityChange: setVisibility,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
  });

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "flex-end", padding: "8px 12px 0" }}>
        <div className="colmenu">
          <button className="btn sm ghost" onClick={() => setMenuOpen((o) => !o)}>列 ▾</button>
          {menuOpen && (
            <div className="colmenu-pop" onMouseLeave={() => setMenuOpen(false)}>
              {table.getAllLeafColumns().filter((c) => c.id !== "actions").map((col) => (
                <label key={col.id}>
                  <input
                    type="checkbox"
                    checked={col.getIsVisible()}
                    onChange={col.getToggleVisibilityHandler()}
                  />
                  {colLabel(col.id)}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="table-wrap">
        <table className="txns">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sortable = SORTABLE.has(h.column.id);
                  const arrow = sort === h.column.id ? (order === "asc" ? " ↑" : " ↓") : "";
                  return (
                    <th
                      key={h.id}
                      className={sortable ? "sortable" : ""}
                      onClick={sortable ? () => onSort(h.column.id) : undefined}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {arrow}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, i) => (
              <motion.tr
                key={row.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i * 0.01, 0.2) }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </motion.tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !props.loading && <div className="empty">没有匹配的条目</div>}
      </div>

      <div className="pager">
        <span>共 {total} 条 · 显示 {from}–{to}</span>
        <span className="spacer" style={{ flex: 1 }} />
        <button className="btn sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>
          上一页
        </button>
        <button className="btn sm" disabled={to >= total} onClick={() => onPage(offset + limit)}>
          下一页
        </button>
      </div>
    </div>
  );
}

function colLabel(id: string): string {
  return (
    { date: "日期", direction: "方向", content: "内容", category: "分类", amount: "金额", base_cny: "人民币" } as Record<
      string,
      string
    >
  )[id] ?? id;
}
