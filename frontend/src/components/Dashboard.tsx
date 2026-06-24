import { useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import { api } from "../api";
import type { Dashboard as DashboardData } from "../types";
import EChart from "./EChart";

interface Props {
  notify: (msg: string, error?: boolean) => void;
  onNavigate: (view: "list" | "aa" | "stats" | "budget") => void;
}

const money2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = (v: number) =>
  Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + "万" : String(Math.round(v));
const fmtPct = (p: number | null | undefined) => (p == null ? "—" : (p * 100).toFixed(0) + "%");

function Bar({ pct, over }: { pct: number | null; over: boolean }) {
  const w = pct == null ? 0 : Math.min(pct, 1) * 100;
  const color = over ? "var(--expense)" : pct != null && pct >= 0.85 ? "var(--warn)" : "var(--income)";
  return (
    <div className="budget-bar">
      <div className="budget-bar-fill" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

export default function Dashboard({ notify, onNavigate }: Props) {
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    api.dashboard().then(setData).catch((e) => notify(e.message, true));
  }, []);

  const topTotal = useMemo(
    () => (data?.top_categories ?? []).reduce((s, c) => s + c.total, 0),
    [data]
  );

  const donutOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { trigger: "item", formatter: (p: any) => `${p.name}<br/>¥${money2(p.value)} · ${p.percent}%` },
    series: [{
      type: "pie", radius: ["52%", "78%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      data: (data?.top_categories ?? []).map((c) => ({
        name: c.category, value: c.total, itemStyle: { color: c.color },
      })),
    }],
    graphic: {
      type: "text", left: "center", top: "center",
      style: { text: `¥${compact(topTotal)}`, fontSize: 16, fontWeight: 700, fill: "#1f2430" },
    },
  }), [data, topTotal]);

  if (!data) return <div className="empty">加载中…</div>;

  const cur = data.current;
  const delta = cur.delta ?? 0;
  const up = delta > 0;
  const bud = data.budget;
  const ov = bud.overall;
  const aa = data.aa_unsettled;
  const budgetedCats = bud.categories.filter((c) => c.limit != null);

  return (
    <div className="dash">
      {/* Headline: this fiscal month + delta vs last */}
      <div className="dash-grid">
        <div className="card dash-kpi">
          <div className="dash-kpi-label">本财政月支出（{cur.range_start} → {cur.range_end}）</div>
          <div className="dash-kpi-value">¥{money2(cur.total_cny)}</div>
          <div className={`dash-delta ${up ? "up" : "down"}`}>
            {up ? "▲" : "▼"} ¥{money2(Math.abs(delta))}
            <span className="muted"> 较上月 {fmtPct(cur.delta_pct == null ? null : Math.abs(cur.delta_pct))}</span>
          </div>
          <div className="muted dash-sub">上月 ¥{money2(data.previous.total_cny)}</div>
        </div>

        {/* Overall budget progress */}
        <div className="card dash-kpi">
          <div className="dash-kpi-label">总预算进度</div>
          {bud.has_overall ? (
            <>
              <div className="dash-kpi-value small">
                ¥{money2(Number(ov.actual))} <span className="muted">/ ¥{money2(Number(ov.limit))}</span>
              </div>
              <Bar pct={ov.pct} over={ov.over} />
              <div className={`dash-sub ${ov.over ? "over" : "muted"}`}>
                {ov.over ? `超支 ¥${money2(-Number(ov.remaining))}` : `剩余 ¥${money2(Number(ov.remaining))}`} · {fmtPct(ov.pct)}
              </div>
            </>
          ) : (
            <div className="dash-empty">
              <span className="muted">未设置总预算</span>
              <button className="btn sm" onClick={() => onNavigate("budget")}>去设置</button>
            </div>
          )}
        </div>

        {/* AA unsettled reminder */}
        <div className="card dash-kpi">
          <div className="dash-kpi-label">AA 未结清</div>
          {aa.count > 0 ? (
            <>
              <div className="dash-kpi-value small">{aa.count} <span className="muted">笔待结清</span></div>
              <div className="dash-aa-list">
                {aa.by_currency.map((g) => (
                  <span className="bal" key={g.currency}>{g.currency} {money2(Number(g.amount))} · {g.count}笔</span>
                ))}
              </div>
              <button className="btn sm" style={{ marginTop: 10 }} onClick={() => onNavigate("aa")}>去结清</button>
            </>
          ) : (
            <div className="dash-empty"><span className="muted">没有未结清的 AA 🎉</span></div>
          )}
        </div>
      </div>

      {/* Top categories + per-category budget bars */}
      <div className="stats-grid2">
        <div className="card stats-card">
          <div className="stats-head">
            <div className="section-title" style={{ margin: 0 }}>本月主要分类</div>
            <button className="btn sm ghost" onClick={() => onNavigate("stats")}>更多统计 →</button>
          </div>
          {data.top_categories.length > 0 ? (
            <div className="dash-cats">
              <EChart option={donutOption} height={220} resetKey="dash-donut" />
              <div className="dash-cat-legend">
                {data.top_categories.map((c) => (
                  <div className="dash-cat-item" key={String(c.category_id)}>
                    <span className="swatch" style={{ background: c.color }} />
                    <span className="grow">{c.category}</span>
                    <b>¥{money2(c.total)}</b>
                    <span className="muted">{topTotal > 0 ? ((c.total / topTotal) * 100).toFixed(0) : 0}%</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty">本月还没有支出</div>
          )}
        </div>

        <div className="card stats-card">
          <div className="stats-head">
            <div className="section-title" style={{ margin: 0 }}>分类预算进度</div>
            <button className="btn sm ghost" onClick={() => onNavigate("budget")}>管理预算 →</button>
          </div>
          {budgetedCats.length > 0 ? (
            <div className="budget-rows tight">
              {budgetedCats.map((c) => (
                <div className="dash-budget-row" key={String(c.category_id)}>
                  <div className="dash-budget-top">
                    <span className="swatch" style={{ background: c.color ?? "#ccc" }} />
                    <span className="grow">{c.category}</span>
                    <span className={c.over ? "over" : "muted"}>
                      ¥{money2(Number(c.actual))} / ¥{money2(Number(c.limit))} · {fmtPct(c.pct)}
                    </span>
                  </div>
                  <Bar pct={c.pct} over={c.over} />
                </div>
              ))}
            </div>
          ) : (
            <div className="dash-empty">
              <span className="muted">还没有分类预算</span>
              <button className="btn sm" onClick={() => onNavigate("budget")}>去设置</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
