import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { BudgetStatus, Category, CategoryBudgetStatus } from "../types";

interface Props {
  categories: Category[];
  notify: (msg: string, error?: boolean) => void;
  onChanged?: () => void;
}

type Kind = "absolute" | "percent";
type BudgetCurrency = "CNY" | "USD";
interface Edit { type: Kind; value: string; currency: BudgetCurrency }

const money2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (p: number | null) => (p == null ? "—" : (p * 100).toFixed(0) + "%");

// A budget progress bar. Clamps the fill to 100% but flags overspend in red.
function Bar({ pct, over }: { pct: number | null; over: boolean }) {
  const w = pct == null ? 0 : Math.min(pct, 1) * 100;
  const color = over ? "var(--expense)" : pct != null && pct >= 0.85 ? "var(--warn)" : "var(--income)";
  return (
    <div className="budget-bar">
      <div className="budget-bar-fill" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

export default function BudgetView({ categories, notify, onChanged }: Props) {
  const [status, setStatus] = useState<BudgetStatus | null>(null);
  const [overall, setOverall] = useState("");
  const [overallCurrency, setOverallCurrency] = useState<BudgetCurrency>("CNY");
  const [edits, setEdits] = useState<Record<string, Edit>>({});

  const expenseCats = useMemo(
    () => categories.filter((c) => c.kind === "expense" && c.active),
    [categories]
  );

  // keepDrafts: after saving one row, keep unsaved edits typed in the other
  // rows (only `savedCid`, if any, is reset to the server value).
  function load(keepDrafts = false, savedCid: number | null = null) {
    api.budgetStatus()
      .then((s) => {
        setStatus(s);
        setOverall(s.overall.limit ?? "");
        const m: Record<string, Edit> = {};
        for (const c of s.categories) {
          if (c.category_id == null) continue;
          m[String(c.category_id)] = {
            type: c.amount_type,
            value: c.amount_type === "percent" ? c.percent ?? "" : c.limit ?? "",
            currency: "CNY",
          };
        }
        setOverallCurrency("CNY");
        setEdits((prev) => {
          if (!keepDrafts) return m;
          const merged = { ...m };
          for (const [k, v] of Object.entries(prev)) if (k !== String(savedCid)) merged[k] = v;
          return merged;
        });
      })
      .catch((e) => notify(e.message, true));
  }
  useEffect(() => load(), []);

  const statusByCat = useMemo(() => {
    const m: Record<string, CategoryBudgetStatus> = {};
    for (const c of status?.categories ?? []) if (c.category_id != null) m[String(c.category_id)] = c;
    return m;
  }, [status]);

  // Budgets attached to a category that is no longer an active expense
  // category. They still count toward the dashboard/overview but have no
  // editable row above, so surface them separately with a clear action so they
  // can't become unmanageable leftovers (finding 3).
  const activeIds = useMemo(() => new Set(expenseCats.map((c) => c.id)), [expenseCats]);
  const orphanBudgets = useMemo(
    () => (status?.categories ?? []).filter(
      (c) => c.category_id != null && !activeIds.has(c.category_id)
    ),
    [status, activeIds]
  );

  const setEdit = (cid: number, patch: Partial<Edit>) =>
    setEdits((e) => {
      const prev: Edit = e[cid] ?? { type: "absolute", value: "", currency: "CNY" };
      return { ...e, [cid]: { ...prev, ...patch } };
    });

  async function saveOverall() {
    try {
      if (!overall.trim()) {
        if (status?.overall.budget_id == null) return;
        // An empty box (e.g. right after switching ¥/$) must not silently
        // delete an existing overall budget.
        if (!window.confirm("总预算输入为空，要删除现有的总预算吗？")) return;
        await api.deleteBudget(status.overall.budget_id);
      } else {
        await api.setBudget({
          category_id: null,
          amount_type: "absolute",
          amount: overall.trim(),
          amount_currency: overallCurrency,
          period_end: status?.period_end ?? null,
        });
      }
      notify("总预算已更新");
      load(true);
      onChanged?.();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  async function saveCategory(cid: number) {
    const e = edits[String(cid)] ?? { type: "absolute", value: "", currency: "CNY" };
    if (!e.value.trim()) return;
    try {
      await api.setBudget({
        category_id: cid,
        amount_type: e.type,
        amount: e.type === "absolute" ? e.value.trim() : null,
        amount_currency: e.type === "absolute" ? e.currency : "CNY",
        period_end: status?.period_end ?? null,
        percent: e.type === "percent" ? e.value.trim() : null,
      });
      notify("分类预算已更新");
      load(true, cid);
      onChanged?.();
    } catch (err) {
      notify((err as Error).message, true);
    }
  }

  async function clearCategory(cid: number) {
    const st = statusByCat[String(cid)];
    if (!st) {
      setEdits((e) => ({ ...e, [cid]: { type: "absolute", value: "", currency: "CNY" } }));
      return;
    }
    try {
      await api.deleteBudget(st.budget_id);
      notify("已清除");
      load(true, cid);
      onChanged?.();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  if (!status) return <div className="empty">加载中…</div>;

  const ov = status.overall;
  return (
    <div className="stats">
      <div className="card stats-card">
        <div className="section-title">
          总预算 · 当前财政月（{status.range_start} → {status.range_end}）
        </div>
        <div className="budget-overall">
          <div className="budget-edit">
            <span className="muted">每月总预算</span>
            <div className="seg sm">
              <button className={overallCurrency === "CNY" ? "active" : ""} onClick={() => { setOverallCurrency("CNY"); setOverall(""); }}>¥</button>
              <button className={overallCurrency === "USD" ? "active" : ""} onClick={() => { setOverallCurrency("USD"); setOverall(""); }}>$</button>
            </div>
            <input
              type="number"
              inputMode="decimal"
              placeholder={overallCurrency === "USD" ? "美元金额" : "人民币金额"}
              value={overall}
              onChange={(e) => setOverall(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveOverall()}
            />
            <button className="btn primary sm" onClick={saveOverall}>保存</button>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            美元预算会按当前财政月结尾日（{status.period_end}）的美元汇率折算为人民币保存。
          </div>
          {status.has_overall ? (
            <div className="budget-progress">
              <Bar pct={ov.pct} over={ov.over} />
              <div className="budget-meta">
                <span>已花 <b>¥{money2(Number(ov.actual))}</b> / ¥{money2(Number(ov.limit))}</span>
                <span className={ov.over ? "over" : "muted"}>
                  {ov.over ? `超支 ¥${money2(-Number(ov.remaining))}` : `剩余 ¥${money2(Number(ov.remaining))}`}
                  {" · "}{fmtPct(ov.pct)}
                </span>
              </div>
            </div>
          ) : (
            <div className="muted" style={{ marginTop: 6 }}>未设置总预算，分类百分比预算需要先设置总预算才能换算。</div>
          )}
        </div>
      </div>

      <div className="card stats-card">
        <div className="section-title">分类预算（绝对值 ¥ 或 占总预算 %）</div>
        <div className="budget-rows">
          {expenseCats.map((c) => {
            const e = edits[String(c.id)] ?? { type: "absolute" as Kind, value: "", currency: "CNY" as BudgetCurrency };
            const st = statusByCat[String(c.id)];
            const budgeted = !!st;
            return (
              <div className="budget-row" key={c.id}>
                <span className="swatch" style={{ background: c.color ?? "#ccc" }} />
                <span className="budget-name">{c.name}</span>
                <div className="seg sm">
                  <button className={e.type === "absolute" && e.currency === "CNY" ? "active" : ""} onClick={() => setEdit(c.id, { type: "absolute", currency: "CNY", value: "" })}>¥</button>
                  <button className={e.type === "absolute" && e.currency === "USD" ? "active" : ""} onClick={() => setEdit(c.id, { type: "absolute", currency: "USD", value: "" })}>$</button>
                  <button className={e.type === "percent" ? "active" : ""} onClick={() => setEdit(c.id, { type: "percent", value: "" })}>%</button>
                </div>
                <input
                  className="budget-input"
                  type="number"
                  inputMode="decimal"
                  placeholder={e.type === "percent" ? "%" : e.currency === "USD" ? "$" : "¥"}
                  value={e.value}
                  onChange={(ev) => setEdit(c.id, { value: ev.target.value })}
                  onKeyDown={(ev) => ev.key === "Enter" && saveCategory(c.id)}
                />
                <button className="btn sm" onClick={() => saveCategory(c.id)}>保存</button>
                {budgeted && <button className="btn sm ghost danger" onClick={() => clearCategory(c.id)}>清除</button>}
                <div className="budget-row-progress">
                  {budgeted ? (
                    <>
                      <Bar pct={st.pct} over={st.over} />
                      <span className="budget-row-meta">
                        ¥{money2(Number(st.actual))}
                        {st.limit != null ? ` / ¥${money2(Number(st.limit))} · ${fmtPct(st.pct)}` : " · 待总预算"}
                        {st.amount_type === "percent" && st.percent ? ` (${st.percent}%)` : ""}
                      </span>
                    </>
                  ) : (
                    <span className="budget-row-meta muted">未设预算</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {orphanBudgets.length > 0 && (
        <div className="card stats-card">
          <div className="section-title">已停用分类的预算</div>
          <div className="muted" style={{ marginBottom: 8 }}>
            以下分类已停用，但仍设有预算并计入概览/统计。可在此清除。
          </div>
          <div className="budget-rows">
            {orphanBudgets.map((st) => (
              <div className="budget-row orphan" key={st.budget_id}>
                <span className="swatch" style={{ background: st.color ?? "#ccc" }} />
                <span className="budget-name">{st.category ?? `分类 #${st.category_id}`}</span>
                <button className="btn sm ghost danger" onClick={() => clearCategory(st.category_id!)}>清除</button>
                <div className="budget-row-progress">
                  <Bar pct={st.pct} over={st.over} />
                  <span className="budget-row-meta">
                    ¥{money2(Number(st.actual))}
                    {st.limit != null ? ` / ¥${money2(Number(st.limit))} · ${fmtPct(st.pct)}` : " · 待总预算"}
                    {st.amount_type === "percent" && st.percent ? ` (${st.percent}%)` : ""}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
