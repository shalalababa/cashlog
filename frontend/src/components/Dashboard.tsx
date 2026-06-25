import { useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import { api } from "../api";
import type { Dashboard as DashboardData } from "../types";
import EChart from "./EChart";

interface Props {
  notify: (msg: string, error?: boolean) => void;
  onNavigate: (view: "list" | "aa" | "stats" | "budget") => void;
}

type DisplayCurrency = "CNY" | "USD";

const money2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = (v: number) =>
  Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(Math.round(v));
const fmtPct = (p: number | null | undefined) =>
  p == null ? "-" : `${(p * 100).toFixed(0)}%`;
const symbol = (c: DisplayCurrency) => (c === "USD" ? "$" : "¥");
const fmtMoney = (n: number, c: DisplayCurrency) => `${symbol(c)}${money2(n)}`;

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
  const [displayCurrency, setDisplayCurrency] = useState<DisplayCurrency>("CNY");

  useEffect(() => {
    api.dashboard().then(setData).catch((e) => notify(e.message, true));
  }, []);

  const usdRate = data?.current.usd_rate ?? null;
  const toDisplayWithRate = (cny: number, rate: number | null = usdRate): number | null =>
    displayCurrency === "USD" ? (rate ? cny / rate : null) : cny;
  const toDisplay = (cny: number): number | null => toDisplayWithRate(cny);

  const topTotal = useMemo(
    () => (data?.top_categories ?? []).reduce((s, c) => s + c.total, 0),
    [data]
  );
  const topDisplayTotal = toDisplay(topTotal) ?? 0;

  const donutOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: {
      trigger: "item",
      formatter: (p: any) => `${p.name}<br/>${fmtMoney(p.value, displayCurrency)} · ${p.percent}%`,
    },
    series: [{
      type: "pie", radius: ["52%", "78%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      data: (data?.top_categories ?? []).map((c) => ({
        name: c.category,
        value: toDisplay(c.total) ?? 0,
        itemStyle: { color: c.color },
      })),
    }],
    graphic: {
      type: "text", left: "center", top: "center",
      style: {
        text: `${symbol(displayCurrency)}${compact(topDisplayTotal)}`,
        fontSize: 16,
        fontWeight: 700,
        fill: "#1f2430",
      },
    },
  }), [data, displayCurrency, usdRate, topDisplayTotal]);

  const cumulativeOption = useMemo<echarts.EChartsOption>(() => {
    const currentRate = data?.current.usd_rate ?? null;
    const previousRate = data?.previous.usd_rate ?? null;
    const values = (items: number[], rate: number | null) =>
      items.map((v) => {
        const shown = toDisplayWithRate(v, rate);
        return shown == null ? null : Number(shown.toFixed(2));
      });
    return {
      color: ["#4361ee", "#9aa3b2"],
      tooltip: {
        trigger: "axis",
        formatter: (params: any) => {
          const rows = Array.isArray(params) ? params : [params];
          return rows.map((p: any) => {
            const val = p.data == null ? "-" : fmtMoney(Number(p.data), displayCurrency);
            return `${p.marker}${p.seriesName}: ${val}`;
          }).join("<br/>");
        },
      },
      legend: { top: 0, right: 0 },
      grid: { left: 42, right: 18, top: 34, bottom: 26 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data?.cumulative.days.map((d) => `第${d}天`) ?? [],
      },
      yAxis: {
        type: "value",
        axisLabel: { formatter: (v: number) => `${symbol(displayCurrency)}${compact(v)}` },
        splitLine: { lineStyle: { color: "#edf0f6" } },
      },
      series: [
        {
          name: data?.cumulative.current.label ?? "本财政月",
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 3 },
          areaStyle: { opacity: 0.12 },
          data: values(data?.cumulative.current.values ?? [], currentRate),
        },
        {
          name: data?.cumulative.previous.label ?? "上财政月",
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, type: "dashed" },
          data: values(data?.cumulative.previous.values ?? [], previousRate),
        },
      ],
    };
  }, [data, displayCurrency, usdRate]);

  if (!data) return <div className="empty">加载中...</div>;

  const cur = data.current;
  const curTotal = displayCurrency === "USD" ? cur.total_usd : cur.total_cny;
  const prevTotal = displayCurrency === "USD" ? data.previous.total_usd : data.previous.total_cny;
  const delta = curTotal != null && prevTotal != null ? curTotal - prevTotal : null;
  const up = (delta ?? 0) > 0;
  const bud = data.budget;
  const ov = bud.overall;
  const aa = data.aa_unsettled;
  const budgetedCats = bud.categories.filter((c) => c.limit != null);
  const rateLabelDate = cur.usd_rate_date ?? cur.rate_lookup_date;

  return (
    <div className="dash">
      <div className="dash-currency-bar">
        <div className="muted">显示金额</div>
        {displayCurrency === "USD" && cur.usd_rate && (
          <span className="muted">按 {rateLabelDate} 汇率 {cur.usd_rate} 换算</span>
        )}
        {displayCurrency === "USD" && cur.rate_stale && (
          <span className="badge stale">旧汇率</span>
        )}
        <span className="spacer" />
        <div className="seg">
          <button className={displayCurrency === "CNY" ? "active" : ""} onClick={() => setDisplayCurrency("CNY")}>人民币</button>
          <button
            className={displayCurrency === "USD" ? "active" : ""}
            onClick={() => setDisplayCurrency("USD")}
            disabled={!cur.usd_rate}
            title={!cur.usd_rate ? "当前财政月缺少美元汇率" : undefined}
          >
            美元
          </button>
        </div>
      </div>

      <div className="dash-grid">
        <div className="card dash-kpi">
          <div className="dash-kpi-label">本财政月支出（{cur.range_start} 至 {cur.range_end}）</div>
          <div className="dash-kpi-value">{curTotal == null ? "-" : fmtMoney(curTotal, displayCurrency)}</div>
          {delta == null ? (
            <div className="muted dash-sub">缺少上月或本月美元汇率，无法换算对比</div>
          ) : (
            <div className={`dash-delta ${up ? "up" : "down"}`}>
              {up ? "▲" : "▼"} {fmtMoney(Math.abs(delta), displayCurrency)}
              <span className="muted"> 较上月 {fmtPct(prevTotal ? Math.abs(delta / prevTotal) : null)}</span>
            </div>
          )}
          <div className="muted dash-sub">上月 {prevTotal == null ? "-" : fmtMoney(prevTotal, displayCurrency)}</div>
        </div>

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
            <div className="dash-empty"><span className="muted">没有未结清的 AA</span></div>
          )}
        </div>
      </div>

      <div className="card stats-card">
        <div className="stats-head">
          <div>
            <div className="section-title" style={{ margin: 0 }}>财政月累计支出对比</div>
            <div className="muted dash-sub">
              {data.cumulative.current.range_start} 至 {data.cumulative.current.range_end}
              <span> · 按财政月第 N 天对齐上个财政月</span>
            </div>
          </div>
          <button className="btn sm ghost" onClick={() => onNavigate("stats")}>更多统计</button>
        </div>
        <EChart
          option={cumulativeOption}
          height={260}
          resetKey={`dash-cumulative-${displayCurrency}`}
        />
      </div>

      <div className="stats-grid2">
        <div className="card stats-card">
          <div className="stats-head">
            <div className="section-title" style={{ margin: 0 }}>本月主要分类</div>
            <button className="btn sm ghost" onClick={() => onNavigate("stats")}>更多统计</button>
          </div>
          {data.top_categories.length > 0 ? (
            <div className="dash-cats">
              <EChart option={donutOption} height={220} resetKey={`dash-donut-${displayCurrency}`} />
              <div className="dash-cat-legend">
                {data.top_categories.map((c) => {
                  const shown = toDisplay(c.total);
                  return (
                    <div className="dash-cat-item" key={String(c.category_id)}>
                      <span className="swatch" style={{ background: c.color }} />
                      <span className="grow">{c.category}</span>
                      <b>{shown == null ? "-" : fmtMoney(shown, displayCurrency)}</b>
                      <span className="muted">{topTotal > 0 ? ((c.total / topTotal) * 100).toFixed(0) : 0}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="empty">本月还没有支出</div>
          )}
        </div>

        <div className="card stats-card">
          <div className="stats-head">
            <div className="section-title" style={{ margin: 0 }}>分类预算进度</div>
            <button className="btn sm ghost" onClick={() => onNavigate("budget")}>管理预算</button>
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
