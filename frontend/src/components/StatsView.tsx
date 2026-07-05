import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { api } from "../api";
import type { Category, CategoryStat, CategoryTrend, FiscalMonth, RateInfo } from "../types";
import EChart from "./EChart";

interface Props {
  categories: Category[];
  notify: (msg: string, error?: boolean) => void;
}

type Gran = "day" | "week" | "month";
type Mode = "fiscal" | "free";
type DisplayCurrency = "CNY" | "USD";

const catKey = (id: number | null) => (id == null ? "null" : String(id));
const money2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inputMoney = (n: number | null | undefined) =>
  n == null || !Number.isFinite(n) ? "" : n.toFixed(2).replace(/\.00$/, "");
const compact = (v: number) =>
  Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(Math.round(v));
const pct = (r: number | null) => (r == null ? "-" : (r * 100).toFixed(1) + "%");
const symbol = (c: DisplayCurrency) => (c === "USD" ? "$" : "¥");
const fmtMoney = (n: number, c: DisplayCurrency) => `${symbol(c)}${money2(n)}`;

function todayISO() {
  return new Date().toLocaleDateString("sv"); // YYYY-MM-DD, local
}

function shiftDays(iso: string, days: number) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("sv");
}

function nextFiscalEnd(fiscals: FiscalMonth[]) {
  if (!fiscals.length) {
    const today = new Date();
    const candidate = new Date(today.getFullYear(), today.getMonth(), 5);
    if (today.getDate() >= 5) candidate.setMonth(candidate.getMonth() + 1);
    return candidate.toLocaleDateString("sv");
  }
  const last = fiscals[fiscals.length - 1].period_end.split("-").map(Number);
  const d = new Date(last[0], last[1], last[2]); // month is 0-based; last[1] advances one month.
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
  const [displayCurrency, setDisplayCurrency] = useState<DisplayCurrency>("CNY");
  const [rangeRate, setRangeRate] = useState<RateInfo | null>(null);
  const [fiscalEditMode, setFiscalEditMode] = useState(false);
  const [creditDrafts, setCreditDrafts] = useState<Record<string, string>>({});
  const [savingCredit, setSavingCredit] = useState<Set<string>>(new Set());

  const [breakdown, setBreakdown] = useState<CategoryStat[]>([]);
  const [trend, setTrend] = useState<CategoryTrend | null>(null);
  // Default-hide 学费/特殊 from full metadata, not from range-scoped breakdown.
  const [hidden, setHidden] = useState<Set<string>>(
    () => new Set(categories.filter((c) => c.kind === "expense" && c.exclude_stats)
      .map((c) => catKey(c.id)))
  );
  const bdSeq = useRef(0);
  const trSeq = useRef(0);
  const rateSeq = useRef(0);

  function loadFiscals() {
    api.fiscal().then((f) => {
      setFiscals(f);
      if (f.length && fiscals.length === 0) {
        setFrom(f[0].range_start);
        setTo(f[f.length - 1].range_end);
      }
    }).catch((e) => notify(e.message, true));
  }

  useEffect(() => {
    loadFiscals();
    // Initial load only. Later saves call loadFiscals explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedFiscal = useMemo(
    () => fiscalSel === "all" ? null : fiscals.find((f) => f.period_end === fiscalSel) ?? null,
    [fiscalSel, fiscals]
  );

  const range = useMemo<{ from: string; to: string }>(() => {
    if (mode === "free") return { from, to };
    if (!fiscals.length) return { from, to };
    if (fiscalSel === "all")
      return { from: fiscals[0].range_start, to: fiscals[fiscals.length - 1].range_end };
    return selectedFiscal ? { from: selectedFiscal.range_start, to: selectedFiscal.range_end } : { from, to };
  }, [mode, from, to, fiscalSel, fiscals, selectedFiscal]);

  const rateLookupDate = selectedFiscal?.period_end ?? range.to;
  const rangeUsdRate = rangeRate?.found && rangeRate.rate ? Number(rangeRate.rate) : null;
  const rateLabelDate = rangeRate?.rate_date ?? rateLookupDate;

  useEffect(() => {
    if (!rateLookupDate) return;
    const seq = ++rateSeq.current;
    api.rate("USD", rateLookupDate)
      .then((r) => { if (seq === rateSeq.current) setRangeRate(r); })
      .catch((e) => { if (seq === rateSeq.current) notify(e.message, true); });
  }, [rateLookupDate]);

  useEffect(() => {
    if (displayCurrency === "USD" && rangeRate && !rangeUsdRate) setDisplayCurrency("CNY");
  }, [displayCurrency, rangeRate, rangeUsdRate]);

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

  const toDisplay = (cny: number, rate: number | null = rangeUsdRate): number | null =>
    displayCurrency === "USD" ? (rate ? cny / rate : null) : cny;

  const visibleBreakdown = useMemo(
    () => breakdown.filter((c) => !isHidden(c.category_id) && c.total > 0),
    [breakdown, hidden]
  );
  const rangeTotal = useMemo(
    () => visibleBreakdown.reduce((s, c) => s + (toDisplay(c.total) ?? 0), 0),
    [visibleBreakdown, displayCurrency, rangeUsdRate]
  );

  const donutOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { trigger: "item", formatter: (p: any) => `${p.name}<br/>${fmtMoney(p.value, displayCurrency)} · ${p.percent}%` },
    series: [{
      type: "pie", radius: ["46%", "72%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      data: visibleBreakdown.map((c) => ({ name: c.category, value: toDisplay(c.total) ?? 0, itemStyle: { color: c.color } })),
    }],
    graphic: {
      type: "text", left: "center", top: "center",
      style: { text: `${symbol(displayCurrency)}${compact(rangeTotal)}`, fontSize: 18, fontWeight: 700, fill: "#1f2430" },
    },
  }), [visibleBreakdown, rangeTotal, displayCurrency, rangeUsdRate]);

  const treemapOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { formatter: (p: any) => `${p.name}<br/>${fmtMoney(p.value, displayCurrency)}` },
    series: [{
      type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false },
      width: "100%", height: "100%", top: 4, left: 0, right: 0, bottom: 4,
      label: { show: true, formatter: "{b}", color: "#fff", fontWeight: 600 },
      itemStyle: { borderColor: "#fff", borderWidth: 2, gapWidth: 2 },
      data: visibleBreakdown.map((c) => ({ name: c.category, value: toDisplay(c.total) ?? 0, itemStyle: { color: c.color } })),
    }],
  }), [visibleBreakdown, displayCurrency, rangeUsdRate]);

  const totalTrendOption = useMemo<echarts.EChartsOption>(() => {
    const periods = trend?.periods ?? [];
    const vis = (trend?.series ?? []).filter((s) => !isHidden(s.category_id));
    const totals = periods.map((_, i) => vis.reduce((s, ser) => s + (ser.values[i] || 0), 0));
    return {
      tooltip: { trigger: "axis", valueFormatter: (v: any) => fmtMoney(v as number, displayCurrency) },
      grid: { left: 56, right: 18, top: 18, bottom: 30 },
      xAxis: { type: "category", data: periods, boundaryGap: gran !== "day", axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${symbol(displayCurrency)}${compact(v)}` }, splitLine: { lineStyle: { color: "#eef0f5" } } },
      series: [{
        type: "line", smooth: true, data: totals.map((v) => toDisplay(v)),
        color: "#4361ee", showSymbol: periods.length <= 60,
        areaStyle: { opacity: 0.16 }, lineStyle: { width: 2 },
      }],
    };
  }, [trend, hidden, gran, displayCurrency, rangeUsdRate]);

  const stackOption = useMemo<echarts.EChartsOption>(() => {
    const periods = trend?.periods ?? [];
    const vis = (trend?.series ?? []).filter((s) => !isHidden(s.category_id));
    const denom = periods.map((_, i) => vis.reduce((s, ser) => s + Math.max(ser.values[i] || 0, 0), 0));
    return {
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: any) => (shareMode ? (v as number).toFixed(1) + "%" : fmtMoney(v as number, displayCurrency)),
      },
      grid: { left: 56, right: 18, top: 18, bottom: 30 },
      xAxis: { type: "category", data: periods, boundaryGap: false, axisLabel: { hideOverlap: true } },
      yAxis: {
        type: "value", max: shareMode ? 100 : undefined,
        axisLabel: { formatter: (v: number) => (shareMode ? v + "%" : `${symbol(displayCurrency)}${compact(v)}`) },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      series: vis.map((s) => ({
        name: s.category, type: "line", stack: "all", showSymbol: false,
        lineStyle: { width: 0 }, areaStyle: { opacity: 0.85 }, color: s.color, emphasis: { focus: "series" },
        data: s.values.map((v, i) =>
          shareMode ? (denom[i] > 0 ? +((Math.max(v, 0) / denom[i]) * 100).toFixed(2) : 0) : toDisplay(v)),
      })),
    };
  }, [trend, hidden, shareMode, displayCurrency, rangeUsdRate]);

  const fiscalChartOption = useMemo<echarts.EChartsOption>(() => ({
    tooltip: {
      trigger: "axis",
      formatter: (ps: any) => {
        const cny = ps.find((p: any) => p.seriesName === "总支出 ¥")?.value;
        const r = ps.find((p: any) => p.seriesName === "信用卡占比")?.value;
        return `${ps[0].axisValue}<br/>总支出 ¥${money2(cny ?? 0)}<br/>占比 ${r == null ? "-" : r + "%"}`;
      },
    },
    grid: { left: 60, right: 56, top: 24, bottom: 30 },
    legend: { data: ["总支出 ¥", "信用卡占比"], top: 0 },
    xAxis: { type: "category", data: fiscals.map((f) => f.period_end), axisLabel: { hideOverlap: true } },
    yAxis: [
      { type: "value", name: "¥", axisLabel: { formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: "#eef0f5" } } },
      { type: "value", name: "%", axisLabel: { formatter: "{value}%" }, splitLine: { show: false } },
    ],
    series: [
      { name: "总支出 ¥", type: "bar", color: "#4361ee", data: fiscals.map((f) => f.total_cny), itemStyle: { borderRadius: [4, 4, 0, 0] } },
      { name: "信用卡占比", type: "line", yAxisIndex: 1, smooth: true, color: "#f4a23a",
        data: fiscals.map((f) => (f.ratio == null ? null : +(f.ratio * 100).toFixed(1))) },
    ],
  }), [fiscals]);

  const hasRangeData = visibleBreakdown.length > 0;
  const canDisplayUsd = !!rangeUsdRate;

  function fiscalDrafts(rows: FiscalMonth[]) {
    return Object.fromEntries(rows.map((f) => [f.period_end, inputMoney(f.credit_card)]));
  }

  function toggleFiscalEditMode() {
    if (fiscalEditMode) {
      setFiscalEditMode(false);
      setCreditDrafts({});
      return;
    }
    setCreditDrafts(fiscalDrafts(fiscals));
    setFiscalEditMode(true);
  }

  async function addFiscalMonth() {
    const period = nextFiscalEnd(fiscals);
    try {
      await api.saveFiscal(period, {
        total_cny: null,
        credit_card: "0",
        credit_card_currency: "USD",
      });
      notify("财政月已添加");
      setFiscalSel(period);
      setCreditDrafts((d) => ({ ...d, [period]: "0" }));
      loadFiscals();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  async function saveCreditCard(f: FiscalMonth) {
    const draft = (creditDrafts[f.period_end] ?? "").trim();
    const nextValue = draft || "0";
    if (nextValue === (inputMoney(f.credit_card) || "0")) return;

    setSavingCredit((s) => new Set(s).add(f.period_end));
    try {
      await api.saveFiscal(f.period_end, {
        total_cny: f.total_cny_overridden ? inputMoney(f.total_cny_override) : null,
        credit_card: nextValue,
        credit_card_currency: "USD",
      });
      notify("信用卡金额已保存");
      loadFiscals();
    } catch (e) {
      notify((e as Error).message, true);
      setCreditDrafts((d) => ({ ...d, [f.period_end]: inputMoney(f.credit_card) }));
    } finally {
      setSavingCredit((s) => {
        const n = new Set(s);
        n.delete(f.period_end);
        return n;
      });
    }
  }

  return (
    <div className="stats">
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
        <span className="muted">{range.from} → {range.to}</span>
        <span className="spacer" />
        {displayCurrency === "USD" && rangeUsdRate && (
          <span className="muted">按 {rateLabelDate} 汇率 {rangeUsdRate} 换算</span>
        )}
        {displayCurrency === "USD" && rangeRate?.stale && <span className="badge stale">旧汇率</span>}
        <div className="seg">
          <button className={displayCurrency === "CNY" ? "active" : ""} onClick={() => setDisplayCurrency("CNY")}>人民币</button>
          <button
            className={displayCurrency === "USD" ? "active" : ""}
            onClick={() => setDisplayCurrency("USD")}
            disabled={!canDisplayUsd}
            title={!canDisplayUsd ? "当前区间缺少美元汇率" : undefined}
          >
            美元
          </button>
        </div>
      </div>

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
                title={`${fmtMoney(toDisplay(c.total) ?? 0, displayCurrency)} · ${c.count} 笔`}
              >
                {c.category}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="stats-grid2">
        <div className="card stats-card">
          <div className="section-title">分类占比（环形）</div>
          {hasRangeData ? <EChart option={donutOption} height={300} resetKey={`donut-${displayCurrency}`} />
            : <div className="empty">区间内没有支出</div>}
        </div>
        <div className="card stats-card">
          <div className="section-title">分类金额（矩形树图）</div>
          {hasRangeData ? <EChart option={treemapOption} height={300} resetKey={`treemap-${displayCurrency}`} />
            : <div className="empty">区间内没有支出</div>}
        </div>
      </div>

      <div className="card stats-card">
        <div className="stats-head">
          <div className="section-title" style={{ margin: 0 }}>支出趋势</div>
          <div className="seg">
            <button className={gran === "day" ? "active" : ""} onClick={() => setGran("day")}>日</button>
            <button className={gran === "week" ? "active" : ""} onClick={() => setGran("week")}>周</button>
            <button className={gran === "month" ? "active" : ""} onClick={() => setGran("month")}>月</button>
          </div>
        </div>
        {trend && trend.periods.length > 0 ? <EChart option={totalTrendOption} height={280} resetKey={`trend-${displayCurrency}`} />
          : <div className="empty">区间内没有支出</div>}
      </div>

      <div className="card stats-card">
        <div className="stats-head">
          <div className="section-title" style={{ margin: 0 }}>分类{shareMode ? "占比" : "金额"}趋势</div>
          <div className="seg">
            <button className={!shareMode ? "active" : ""} onClick={() => setShareMode(false)}>金额</button>
            <button className={shareMode ? "active" : ""} onClick={() => setShareMode(true)}>占比</button>
          </div>
        </div>
        {trend && trend.periods.length > 0 ? <EChart option={stackOption} height={300} resetKey={`${shareMode ? "share" : "amt"}-${displayCurrency}`} />
          : <div className="empty">区间内没有支出</div>}
      </div>

      <div className="card stats-card" style={{ order: 10 }}>
        <div className="stats-head">
          <div className="section-title" style={{ margin: 0 }}>财政月统计</div>
          <div className="fiscal-actions">
            {fiscalEditMode && (
              <button className="btn sm" onClick={addFiscalMonth}>添加财政月</button>
            )}
            <button className={fiscalEditMode ? "btn sm ghost" : "btn sm"} onClick={toggleFiscalEditMode}>
              {fiscalEditMode ? "退出编辑" : "编辑"}
            </button>
          </div>
        </div>
        {fiscals.length > 0 ? (
          <>
            <EChart option={fiscalChartOption} height={240} resetKey="fiscal" />
          <div className="table-wrap">
            <table className="txns stats-table">
              <thead>
                <tr>
                  <th>财政月</th>
                  <th className="num">总支出 ¥</th>
                  <th className="num">总支出 $</th>
                  <th className="num">信用卡 $</th>
                  <th className="num">占总支出</th>
                  <th className="num">当日汇率</th>
                </tr>
              </thead>
              <tbody>
                {[...fiscals].reverse().map((f) => {
                  const saving = savingCredit.has(f.period_end);
                  return (
                    <tr key={f.period_end}>
                      <td>{f.period_end}</td>
                      <td className="num">{money2(f.total_cny)}</td>
                      <td className="num">{f.total_usd == null ? "-" : money2(f.total_usd)}</td>
                      <td className="num">
                        {fiscalEditMode ? (
                          <input
                            className="fiscal-credit-input"
                            type="number"
                            inputMode="decimal"
                            value={creditDrafts[f.period_end] ?? inputMoney(f.credit_card)}
                            disabled={saving}
                            aria-label={`${f.period_end} 信用卡支出美元`}
                            onChange={(e) => setCreditDrafts((d) => ({ ...d, [f.period_end]: e.target.value }))}
                            onBlur={() => saveCreditCard(f)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") e.currentTarget.blur();
                              if (e.key === "Escape") setCreditDrafts((d) => ({ ...d, [f.period_end]: inputMoney(f.credit_card) }));
                            }}
                          />
                        ) : money2(f.credit_card)}
                      </td>
                      <td className="num">{pct(f.ratio)}</td>
                      <td className="num">
                        {f.usd_rate == null ? "-" : f.usd_rate}
                        {f.rate_stale && <span className="badge stale" style={{ marginLeft: 6 }}>旧汇率</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        ) : (
          <div className="empty">还没有财政月。进入编辑模式后可以添加财政月并录入信用卡支出。</div>
        )}
      </div>

    </div>
  );
}
