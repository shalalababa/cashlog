import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { api } from "./api";
import type { Filters, Meta, Txn, TxnPage } from "./types";
import FiltersBar from "./components/Filters";
import TxnTable from "./components/TxnTable";
import TxnForm from "./components/TxnForm";
import ManageView from "./components/ManageView";
import AAView from "./components/AAView";
import StatsView from "./components/StatsView";

const EMPTY_FILTERS: Filters = {
  direction: "",
  search: "",
  category_id: null,
  currency: "",
  date_from: "",
  date_to: "",
  aa: "",
  uncategorized: false,
};

const LIMIT = 50;

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [view, setView] = useState<"list" | "aa" | "stats" | "manage">("list");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState("date");
  const [order, setOrder] = useState("desc");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TxnPage>({ items: [], total: 0, limit: LIMIT, offset: 0 });
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Txn | null>(null);
  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const searchTimer = useRef<number>();

  const notify = (msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => setToast(null), 2200);
  };

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => notify(e.message, true));
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.txns({
        direction: filters.direction,
        search: filters.search,
        category_id: filters.category_id,
        currency: filters.currency,
        date_from: filters.date_from,
        date_to: filters.date_to,
        aa: filters.aa,
        uncategorized: filters.uncategorized,
        sort,
        order,
        limit: LIMIT,
        offset,
      });
      setPage(res);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setLoading(false);
    }
  }, [filters, sort, order, offset]);

  // Debounce search; immediate for everything else.
  useEffect(() => {
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(reload, 180);
    return () => window.clearTimeout(searchTimer.current);
  }, [reload]);

  function patchFilters(patch: Partial<Filters>) {
    setOffset(0);
    setFilters((f) => ({ ...f, ...patch }));
  }

  function onSort(col: string) {
    if (sort === col) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(col);
      setOrder("desc");
    }
    setOffset(0);
  }

  function openNew() {
    setEditing(null);
    setFormOpen(true);
  }
  function openEdit(t: Txn) {
    setEditing(t);
    setFormOpen(true);
  }

  async function onDelete(t: Txn) {
    if (!confirm(`删除「${t.content || t.date}」？`)) return;
    try {
      await api.deleteTxn(t.id);
      notify("已删除");
      reload();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  function onSaved() {
    setFormOpen(false);
    notify(editing ? "已更新" : "已新增");
    reload();
    api.meta().then(setMeta);
  }

  if (!meta) return <div className="app"><div className="empty">加载中…</div></div>;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">Cash<span className="dot">·</span>log</div>
        <div className="tabs">
          <button className={`tab ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
            账目
          </button>
          <button className={`tab ${view === "aa" ? "active" : ""}`} onClick={() => setView("aa")}>
            AA
          </button>
          <button className={`tab ${view === "stats" ? "active" : ""}`} onClick={() => setView("stats")}>
            统计
          </button>
          <button className={`tab ${view === "manage" ? "active" : ""}`} onClick={() => setView("manage")}>
            分类 / 币种 / 人
          </button>
        </div>
        <div className="spacer" />
        {view === "list" && (
          <button className="btn primary" onClick={openNew}>+ 新增</button>
        )}
      </div>

      {view === "list" ? (
        <>
          <FiltersBar
            filters={filters}
            categories={meta.categories}
            currencies={meta.currencies}
            onChange={patchFilters}
            onReset={() => {
              setOffset(0);
              setFilters(EMPTY_FILTERS);
            }}
          />
          <TxnTable
            rows={page.items}
            total={page.total}
            offset={offset}
            limit={LIMIT}
            sort={sort}
            order={order}
            loading={loading}
            onSort={onSort}
            onPage={setOffset}
            onEdit={openEdit}
            onDelete={onDelete}
          />
        </>
      ) : view === "aa" ? (
        <AAView currencies={meta.currencies} categories={meta.categories} notify={notify} />
      ) : view === "stats" ? (
        <StatsView categories={meta.categories} notify={notify} />
      ) : (
        <ManageView
          categories={meta.categories}
          currencies={meta.currencies}
          onChanged={() => api.meta().then(setMeta)}
        />
      )}

      <AnimatePresence>
        {formOpen && (
          <TxnForm
            currencies={meta.currencies}
            categories={meta.categories}
            editing={editing}
            onClose={() => setFormOpen(false)}
            onSaved={onSaved}
          />
        )}
      </AnimatePresence>

      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.msg}</div>}
    </div>
  );
}
