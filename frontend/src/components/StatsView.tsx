import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { api } from "../api";
import type { Category, CategoryStat, CategoryTrend, FiscalMonth } from "../types";
import EChart from "./EChart";

interface Props {
  categories: Category[];
  notify: (msg: string, error?: boolean) => void;
}

type Gran = "day" | "week" | "month";
type Mode = "fiscal" | "free";

const catKey = (id: number | null) => (id == null ? "null" : String(id));
const money2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = (v: number) =>
  Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + "万" : String(Math.round(v));
const pct = (r: number | null) => (r == null ? "—" : (r * 100).toFixed(1) + "%");

function todayISO() {
  return new Date().toLocaleDateString("sv"); // YYYY-MM-DD, local
}
function shiftDays(iso: string, days: number) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("sv");
}

export default function StatsView({ categories, notify }: Props) {
  const [fiscals, setFiscals] = useState<FiscalMonth[]>([]);
  const [mode, setMode] = useState<Mode>("fiscal");
  const [fiscalSel, setFiscalSel] = useState<string>("all"); // "all" or a period_end
  const [from, setFrom] = useState(shiftDays(todayISO(), -180));
  const [to, setTo] = useState(todayISO());
  const [gran, setGran] = useState<Gran>("month");
  const [shareMode, setShareMode] = useState(false);

  const [breakdown, setBreakdown] = useState<CategoryStat[]>([]);
  const [trend, setTrend] = useState<CategoryTrend | null>(null);
  // Default-hide 学费/特殊 from the full category metadata (not a range-scoped
  // breakdown, which can miss an excluded category outside the current window).
  const [hidden, setHidden] = useState<Set<string>>(
    () => new Set(categories.filter((c) => c.kind === "expense" && c.exclude_stats)
      .map((c) => catKey(c.id)))
  );
  const bdSeq = useRef(0);   // ignore stale breakdown responses
  const trSeq = useRef(0);   // ignore stale trend responses

  // Load the fiscal table once; default the free-range to the full ledger span.
  useEffect(() => {
    api.fiscal().then((f) => {
      setFiscals(f);
      if (f.length) {
        setFrom(f[0].range_start);
        setTo(f[f.length - 1].range_end);
      }
    }).catch((e) => notify(e.message, true));
  }, []);

  // Effective inclusive range driving the breakdown + trend charts.
  const range = useMemo<{ from: string; to: string }>(() => {
    if (mode === "free") return { from, to };
    if (!fiscals.length) return { from, to };
    if (fiscalSel === "all")
      return { from: fiscals[0].range_start, to: fiscals[fiscals.length - 1].range_end };
    const fm = fiscals.find((f) => f.period_end === fiscalSel);
    return fm ? { from: fm.range_start, to: fm.range_end } : { from, to };
  }, [mode, from, to, fiscalSel, fiscals]);

  // (re)load range-scoped data. A per-request sequence guards against a slow
  // earlier range overwriting a newer one.
  useEffect(() => {
    if (!range.from || !range.to || range.from > range.to) return;
    const seq = ++bdSeq.current;
    api.categoryBreakdown(range.from, range.to)
      .then((b) => { if (seq === bdSeq.current) setBreakdown(b); })
      .catch((e) => { if (seq === bdSeq.current) notify(e.message, true); });
  }, [range.from, range.to]);

  useEffect(() => {
    if (!range.from || !range.to || range.from > range.to) return;
    const seq = ++trSeq.current;
    api.categoryTrend(range.from, range.to, gran)
      .then((t) => { if (seq === trSeq.current) setTrend(t); })
      .catch((e) => { if (seq === trSeq.current) notify(e.message, true); });
  }, [range.from, range.to, gran]);

  const toggleCat = (id: number | null) =>
    setHidden((h) => {
      const n = new Set(h);
      const k = catKey(id);
      n.has(k) ? n.delete(k) : n.add(k);
      return n;
    });
  const isHidden = (id: number | null) => hidden.has(catKey(id));

  // ---- derived chart data -------------------------------------------------
  const visibleBreakdown = useMemo(
    () => breakdown.filter((c) => !isHidden(c.category_id) && c.total > 0),
    [breakdown, hidden]
  );
  const rangeTotal = useMemo(
    () => visibleBreakdown.reduce((s, c) => s + c.total, 0),
    [visibleBreakdown]
  );

  const donutOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { trigger: "item", formatter: (p: any) => `${p.name}<br/>¥${money2(p.value)} · ${p.percent}%` },
    series: [{
      type: "pie", radius: ["46%", "72%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      data: visibleBreakdown.map((c) => ({ name: c.category, value: c.total, itemStyle: { color: c.color } })),
    }],
    graphic: {
      type: "text", left: "center", top: "center",
      style: { text: `¥${compact(rangeTotal)}`, fontSize: 18, fontWeight: 700, fill: "#1f2430" },
    },
  }), [visibleBreakdown, rangeTotal]);

  const treemapOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { formatter: (p: any) => `${p.name}<br/>¥${money2(p.value)}` },
    series: [{
      type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false },
      width: "100%", height: "100%", top: 4, left: 0, right: 0, bottom: 4,
      label: { show: true, formatter: "{b}", color: "#fff", fontWeight: 600 },
      itemStyle: { borderColor: "#fff", borderWidth: 2, gapWidth: 2 },
      data: visibleBreakdown.map((c) => ({ name: c.category, value: c.total, itemStyle: { color: c.color } })),
    }],
  }), [visibleBreakdown]);

  // total trend = sum of visible series per period
  const totalTrendOption = useMemo<echarts.EChartsOption>(() => {
    const periods = trend?.periods ?? [];
    const vis = (trend?.series ?? []).filter((s) => !isHidden(s.category_id));
    const totals = periods.map((_, i) => vis.reduce((s, ser) => s + (ser.values[i] || 0), 0));
    return {
      tooltip: { trigger: "axis", valueFormatter: (v: any) => "¥" + money2(v as number) },
      grid: { left: 56, right: 18, top: 18, bottom: 30 },
      xAxis: { type: "category", data: periods, boundaryGap: gran !== "day", axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: "#eef0f5" } } },
      series: [{
        type: "line", smooth: true, data: totals, color: "#4361ee",
        showSymbol: periods.length <= 60, areaStyle: { opacity: 0.16 }, lineStyle: { width: 2 },
      }],
    };
  }, [trend, hidden, gran]);

  // share / amount over time (stacked)
  const stackOption = useMemo<echarts.EChartsOption>(() => {
    const periods = trend?.periods ?? [];
    const vis = (trend?.series ?? []).filter((s) => !isHidden(s.category_id));
    const denom = periods.map((_, i) => vis.reduce((s, ser) => s + Math.max(ser.values[i] || 0, 0), 0));
    return {
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: any) => (shareMode ? (v as number).toFixed(1) + "%" : "¥" + money2(v as number)),
      },
      grid: { left: 56, right: 18, top: 18, bottom: 30 },
      xAxis: { type: "category", data: periods, boundaryGap: false, axisLabel: { hideOverlap: true } },
      yAxis: {
        type: "value", max: shareMode ? 100 : undefined,
        axisLabel: { formatter: (v: number) => (shareMode ? v + "%" : compact(v)) },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      series: vis.map((s) => ({
        name: s.category, type: "line", stack: "all", showSymbol: false,
        lineStyle: { width: 0 }, areaStyle: { opacity: 0.85 }, color: s.color, emphasis: { focus: "series" },
        data: s.values.map((v, i) =>
          shareMode ? (denom[i] > 0 ? +((Math.max(v, 0) / denom[i]) * 100).toFixed(2) : 0) : v),
      })),
    };
  }, [trend, hidden, shareMode]);

  const fiscalChartOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: {
      trigger: "axis",
      formatter: (ps: any) => {
        const cny = ps.find((p: any) => p.seriesName === "总支出")?.value ?? 0;
        const r = ps.find((p: any) => p.seriesName === "信用卡占比")?.value;
        return `${ps[0].axisValue}<br/>总支出 ¥${money2(cny)}<br/>占比 ${r == null ? "—" : r + "%"}`;
      },
    },
    grid: { left: 60, right: 56, top: 24, bottom: 30 },
    legend: { data: ["总支出", "信用卡占比"], top: 0 },
    xAxis: { type: "category", data: fiscals.map((f) => f.period_end), axisLabel: { hideOverlap: true } },
    yAxis: [
      { type: "value", name: "¥", axisLabel: { formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: "#eef0f5" } } },
      { type: "value", name: "%", axisLabel: { formatter: "{value}%" }, splitLine: { show: false } },
    ],
    series: [
      { name: "总支出", type: "bar", color: "#4361ee", data: fiscals.map((f) => f.total_cny), itemStyle: { borderRadius: [4, 4, 0, 0] } },
      { name: "信用卡占比", type: "line", yAxisIndex: 1, smooth: true, color: "#f4a23a",
        data: fiscals.map((f) => (f.ratio == null ? null : +(f.ratio * 100).toFixed(1))) },
    ],
  }), [fiscals]);

  const hasRangeData = visibleBreakdown.length > 0;

  return (
    <div className="stats">
      {/* Range controls */}
      <div className="card stats-controls">
        <div className="seg">
          <button className={mode === "fiscal" ? "active" : ""} onClick={() => setMode("fiscal")}>财政月</button>
          <button className={mode === "free" ? "active" : ""} onClick={() => setMode("free")}>自由日期</button>
        </div>
        {mode === "fiscal" ? (
          <label className="check">
            财政月
            <select value={fiscalSel} onChange={(e) => setFiscalSel(e.target.value)}>
              <option value="all">全部</option>
              {[...fiscals].reverse().map((f) => (
                <option key={f.period_end} value={f.period_end}>{f.period_end}</option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="check">从 <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label className="check">到 <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </>
        )}
        <span className="muted" style={{ marginLeft: "auto" }}>
          {range.from} → {range.to}
        </span>
      </div>

      {/* Fiscal-month table + chart (replaces 统计) */}
      {fiscals.length > 0 && (
        <div className="card stats-card">
          <div className="section-title">财政月统计（区间 [上月5日, 本月5日)，排除 学费/特殊）</div>
          <EChart option={fiscalChartOption} height={240} />
          <div className="table-wrap">
            <table className="txns stats-table">
              <thead>
                <tr>
                  <th>财政月</th><th className="num">总支出 ¥</th><th className="num">美元换算 $</th>
                  <th className="num">信用卡 $</th><th className="num">信用卡 ¥</th>
                  <th className="num">占总支出</th><th className="num">当日汇率</th>
                </tr>
              </thead>
              <tbody>
                {[...fiscals].reverse().map((f) => (
                  <tr key={f.period_end}>
                    <td>{f.period_end}</td>
                    <td className="num">{money2(f.total_cny)}</td>
                    <td className="num">{f.total_usd == null ? "—" : money2(f.total_usd)}</td>
                    <td className="num">{money2(f.credit_card)}</td>
                    <td className="num">{f.credit_card_cny == null ? "—" : money2(f.credit_card_cny)}</td>
                    <td className="num">{pct(f.ratio)}</td>
                    <td className="num">
                      {f.usd_rate == null ? "—" : f.usd_rate}
                      {f.rate_stale && <span className="badge stale" style={{ marginLeft: 6 }}>旧汇率</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Category legend / toggle */}
      {breakdown.length > 0 && (
        <div className="card stats-card">
          <div className="stats-head">
            <div className="section-title" style={{ margin: 0 }}>分类（点击可排除 / 恢复）</div>
            <button className="btn sm" onClick={() => { setHidden(new Set()); }}>全部显示</button>
          </div>
          <div className="cat-toggle">
            {breakdown.map((c) => (
              <button
                key={catKey(c.category_id)}
                className={"pick" + (isHidden(c.category_id) ? "" : " on")}
                style={!isHidden(c.category_id) ? { background: c.color, borderColor: c.color, color: "#fff" } : undefined}
                onClick={() => toggleCat(c.category_id)}
                title={`¥${money2(c.total)} · ${c.count} 笔`}
              >
                {c.category}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Donut + treemap */}
      <div className="stats-grid2">
        <div className="card stats-card">
          <div className="section-title">分类占比（环形）</div>
          {hasRangeData ? <EChart option={donutOption} height={300} resetKey="donut" />
            : <div className="empty">区间内没有支出</div>}
        </div>
        <div className="card stats-card">
          <div className="section-title">分类金额（矩形树图）</div>
          {hasRangeData ? <EChart option={treemapOption} height={300} resetKey="treemap" />
            : <div className="empty">区间内没有支出</div>}
        </div>
      </div>

      {/* Total trend */}
      <div className="card stats-card">
        <div className="stats-head">
          <div className="section-title" style={{ margin: 0 }}>支出趋势</div>
          <div className="seg">
            <button className={gran === "day" ? "active" : ""} onClick={() => setGran("day")}>日</button>
            <button className={gran === "week" ? "active" : ""} onClick={() => setGran("week")}>周</button>
            <button className={gran === "month" ? "active" : ""} onClick={() => setGran("month")}>月</button>
          </div>
        </div>
        {trend && trend.periods.length > 0 ? <EChart option={totalTrendOption} height={280} />
          : <div className="empty">区间内没有支出</div>}
      </div>

      {/* Share / amount over time */}
      <div className="card stats-card">
        <div className="stats-head">
          <div className="section-title" style={{ margin: 0 }}>分类{shareMode ? "占比" : "金额"}趋势</div>
          <div className="seg">
            <button className={!shareMode ? "active" : ""} onClick={() => setShareMode(false)}>金额</button>
            <button className={shareMode ? "active" : ""} onClick={() => setShareMode(true)}>占比</button>
          </div>
        </div>
        {trend && trend.periods.length > 0 ? <EChart option={stackOption} height={300} resetKey={shareMode ? "share" : "amt"} />
          : <div className="empty">区间内没有支出</div>}
      </div>
    </div>
  );
}
