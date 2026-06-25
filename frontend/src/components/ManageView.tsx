import { useEffect, useState } from "react";
import { api } from "../api";
import type { Category, Currency, Person } from "../types";

interface Props {
  categories: Category[];
  currencies: Currency[];
  notify: (msg: string, error?: boolean) => void;
  onChanged: () => void;
  onRatesChanged: () => void;
}

const PALETTE = ["#FF6B6B", "#4D96FF", "#6BCB77", "#FFD93D", "#9B5DE5", "#00BBF9", "#F15BB5", "#FF9F1C"];

export default function ManageView({ categories, currencies, notify, onChanged, onRatesChanged }: Props) {
  return (
    <div className="manage-grid">
      <CategorySection kind="expense" title="支出分类" categories={categories} onChanged={onChanged} />
      <div>
        <CategorySection kind="income" title="入账分类" categories={categories} onChanged={onChanged} />
        <div style={{ height: 18 }} />
        <PeopleSection />
        <div style={{ height: 18 }} />
        <CurrencySection currencies={currencies} notify={notify} onRatesChanged={onRatesChanged} />
        <div style={{ height: 18 }} />
        <XlsxSyncSection notify={notify} />
      </div>
    </div>
  );
}

function PeopleSection() {
  const [people, setPeople] = useState<Person[]>([]);
  const [name, setName] = useState("");
  const load = () => api.persons().then(setPeople).catch(() => setPeople([]));
  useEffect(() => {
    load();
  }, []);

  async function add() {
    if (!name.trim()) return;
    try {
      await api.createPerson(name.trim());
      setName("");
      load();
    } catch {
      /* duplicate */
    }
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-title">AA 参与人</div>
      <div className="cat-list">
        {people.map((p) => (
          <div className="cat-row" key={p.id} style={{ opacity: p.active ? 1 : 0.45 }}>
            <span className="name">{p.name}</span>
            {p.is_self === 1 && <span className="badge aa">本人</span>}
            <span className="grow" />
            {p.is_self !== 1 && (
              <button className="btn sm ghost" onClick={() => api.updatePerson(p.id, { active: p.active ? 0 : 1 }).then(load)}>
                {p.active ? "停用" : "启用"}
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="add-cat">
        <input placeholder="新参与人姓名" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn primary sm" onClick={add}>添加</button>
      </div>
    </div>
  );
}

function CategorySection({
  kind,
  title,
  categories,
  onChanged,
}: {
  kind: "expense" | "income";
  title: string;
  categories: Category[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  const list = categories.filter((c) => c.kind === kind);

  async function add() {
    if (!name.trim()) return;
    await api.createCategory({ name: name.trim(), kind, color });
    setName("");
    onChanged();
  }
  async function toggle(c: Category, patch: Partial<Category>) {
    await api.updateCategory(c.id, patch);
    onChanged();
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-title">{title}</div>
      <div className="cat-list">
        {list.map((c) => (
          <div className="cat-row" key={c.id} style={{ opacity: c.active ? 1 : 0.45 }}>
            <span className="swatch" style={{ background: c.color ?? "#ccc" }} />
            <span className="name">{c.name}</span>
            {c.exclude_stats === 1 && <span className="badge uncat">不计统计</span>}
            <span className="grow" />
            <label className="check" title="是否计入财政月统计">
              <input
                type="checkbox"
                checked={c.exclude_stats === 0}
                onChange={(e) => toggle(c, { exclude_stats: e.target.checked ? 0 : 1 })}
              />
              计入统计
            </label>
            <button className="btn sm ghost" onClick={() => toggle(c, { active: c.active ? 0 : 1 })}>
              {c.active ? "停用" : "启用"}
            </button>
          </div>
        ))}
      </div>
      <div className="add-cat">
        <input placeholder="新分类名称" value={name} onChange={(e) => setName(e.target.value)} />
        <div style={{ display: "flex", gap: 4 }}>
          {PALETTE.map((p) => (
            <button
              key={p}
              onClick={() => setColor(p)}
              title={p}
              style={{
                width: 20,
                height: 20,
                borderRadius: 6,
                background: p,
                border: color === p ? "2px solid #1f2430" : "2px solid transparent",
              }}
            />
          ))}
        </div>
        <button className="btn primary sm" onClick={add}>添加</button>
      </div>
    </div>
  );
}

function CurrencySection({
  currencies,
  notify,
  onRatesChanged,
}: {
  currencies: Currency[];
  notify: (msg: string, error?: boolean) => void;
  onRatesChanged: () => void;
}) {
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.rateStatus>> | null>(null);
  const [loading, setLoading] = useState(false);
  const load = () => api.rateStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    load();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const out = await api.refreshRates();
      setStatus(out.status);
      notify(`已刷新汇率：新增 ${out.inserted} 条，更新 ${out.updated} 条，重算 ${out.recomputed_txns} 笔交易`);
      onRatesChanged();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setLoading(false);
    }
  }

  const byCode = new Map((status?.currencies ?? []).map((c) => [c.code, c]));

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="stats-head">
        <div className="section-title" style={{ margin: 0 }}>币种 / 汇率</div>
        <button className="btn sm primary" onClick={refresh} disabled={loading}>
          {loading ? "刷新中..." : "刷新所有汇率"}
        </button>
      </div>
      {status && (status.stale_txn_count > 0 || status.missing_txn_count > 0) && (
        <div className="notice-inline">
          {status.stale_txn_count} 笔旧汇率、{status.missing_txn_count} 笔缺汇率。刷新会从 Frankfurter 拉取历史汇率并重算交易人民币缓存。
        </div>
      )}
      <div className="cat-list">
        {currencies.map((c) => (
          <div className="cat-row" key={c.id}>
            <span className="name">
              {c.name} <span className="muted">({c.code})</span>
            </span>
            {c.is_base === 1 && <span className="badge aa">本位币</span>}
            <span className="grow" />
            {c.is_base !== 1 && byCode.get(c.code) && (
              <span className="muted">
                最近 {byCode.get(c.code)?.last_rate_date ?? "-"}
                {" · 旧汇率 "}{byCode.get(c.code)?.stale_txn_count ?? 0}
              </span>
            )}
            <span className="muted">小数位 {c.minor_unit}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function summaryText(summary: {
  new: number; modified: number; deleted: number; conflict: number;
  unknown_uid: number; anomalies: number; db_only: number; unchanged: number;
}) {
  return `新增 ${summary.new}，修改 ${summary.modified}，删除候选 ${summary.deleted}，冲突 ${summary.conflict}，异常 ${summary.anomalies}，仅数据库 ${summary.db_only}，未变 ${summary.unchanged}`;
}

function XlsxSyncSection({ notify }: { notify: (msg: string, error?: boolean) => void }) {
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.xlsxDiff>> | null>(null);
  const [busy, setBusy] = useState(false);

  async function exportXlsx() {
    setBusy(true);
    try {
      const out = await api.xlsxExport();
      notify(`已同步到表格：支出 ${out.written.expense}，入账 ${out.written.income}`);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  async function diffXlsx() {
    setBusy(true);
    try {
      const out = await api.xlsxDiff();
      setPreview(out);
      notify(`已预览：${summaryText(out.summary)}`);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  async function importXlsx() {
    if (!preview) {
      await diffXlsx();
      return;
    }
    if (preview.summary.conflict || preview.summary.anomalies || preview.summary.unknown_uid) {
      notify("表格存在冲突、异常或未知 UID，请先处理后再导入", true);
      return;
    }
    setBusy(true);
    try {
      const out = await api.xlsxImport();
      setPreview({ summary: out.summary });
      notify(`已从表格同步：新增 ${out.applied.new}，修改 ${out.applied.modified}`);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-title">Excel 同步</div>
      <div className="notice-inline">
        程序以 SQLite/JSON 为主；需要和 xlsx 交换数据时在这里手动同步。
      </div>
      <div className="sync-actions">
        <button className="btn sm primary" disabled={busy} onClick={exportXlsx}>同步到表格</button>
        <button className="btn sm" disabled={busy} onClick={diffXlsx}>从表格同步（预览）</button>
        <button className="btn sm" disabled={busy || !preview} onClick={importXlsx}>应用新增/修改</button>
      </div>
      {preview && (
        <div className="sync-summary">
          {summaryText(preview.summary)}
        </div>
      )}
    </div>
  );
}
