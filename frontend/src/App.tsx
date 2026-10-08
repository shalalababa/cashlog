import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { api } from "./api";
import type { Filters, Meta, RateStatus, Txn, TxnPage } from "./types";
import FiltersBar from "./components/Filters";
import TxnTable from "./components/TxnTable";
import TxnForm from "./components/TxnForm";
import ManageView from "./components/ManageView";
import AAView from "./components/AAView";
import StatsView from "./components/StatsView";
import BudgetView from "./components/BudgetView";
import Dashboard from "./components/Dashboard";
import ScrollTopButton from "./components/ScrollTopButton";

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
  const [rateStatus, setRateStatus] = useState<RateStatus | null>(null);
  const [view, setView] = useState<"dashboard" | "list" | "aa" | "stats" | "budget" | "manage">("dashboard");
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
  const toastTimer = useRef<number>();
  const reloadSeq = useRef(0);

  const notify = (msg: string, error = false) => {
    setToast({ msg, error });
    // One timer: an earlier toast's timer must not hide a newer message early.
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2200);
  };

  const reloadRateStatus = useCallback(() => {
    api.rateStatus().then(setRateStatus).catch(() => setRateStatus(null));
  }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => notify(e.message, true));
    reloadRateStatus();
  }, [reloadRateStatus]);

  const reload = useCallback(async () => {
    const seq = ++reloadSeq.current;   // ignore responses overtaken by a newer request
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
      if (seq !== reloadSeq.current) return;
      // Deleting the last row of the last page leaves an empty page: step back.
      if (!res.items.length && offset > 0 && res.total > 0) {
        setOffset(Math.max(0, Math.floor((res.total - 1) / LIMIT) * LIMIT));
        return;
      }
      setPage(res);
    } catch (e) {
      if (seq === reloadSeq.current) notify((e as Error).message, true);
    } finally {
      if (seq === reloadSeq.current) setLoading(false);
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
    reloadRateStatus();
  }

  if (!meta) return <div className="app"><div className="empty">加载中…</div></div>;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">Cash<span className="dot">·</span>log</div>
        <div className="tabs">
          <button className={`tab ${view === "dashboard" ? "active" : ""}`} onClick={() => setView("dashboard")}>
            概览
          </button>
          <button className={`tab ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
            账目
          </button>
          <button className={`tab ${view === "aa" ? "active" : ""}`} onClick={() => setView("aa")}>
            AA
          </button>
          <button className={`tab ${view === "stats" ? "active" : ""}`} onClick={() => setView("stats")}>
            统计
          </button>
          <button className={`tab ${view === "budget" ? "active" : ""}`} onClick={() => setView("budget")}>
            预算
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

      {view === "dashboard" ? (
        <Dashboard notify={notify} onNavigate={setView} />
      ) : view === "list" ? (
        <>
          {rateStatus && (rateStatus.stale_txn_count > 0 || rateStatus.missing_txn_count > 0) && (
            <div className="notice-banner">
              <span>
                有 {rateStatus.stale_txn_count} 笔旧汇率、{rateStatus.missing_txn_count} 笔缺汇率交易。刷新后会重算人民币换算与统计。
              </span>
              <button className="btn sm" onClick={() => setView("manage")}>去刷新汇率</button>
            </div>
          )}
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
        <AAView currencies={meta.currencies} categories={meta.categories} notify={notify} onTxnsChanged={reload} />
      ) : view === "stats" ? (
        <StatsView categories={meta.categories} notify={notify} />
      ) : view === "budget" ? (
        <BudgetView categories={meta.categories} notify={notify} />
      ) : (
        <ManageView
          categories={meta.categories}
          currencies={meta.currencies}
          notify={notify}
          onChanged={() => api.meta().then(setMeta)}
          onRatesChanged={() => {
            reloadRateStatus();
            reload();
          }}
          onTxnsChanged={() => {
            reload();
            api.meta().then(setMeta);
            reloadRateStatus();
          }}
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

      <ScrollTopButton />
      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.msg}</div>}
    </div>
  );
}
