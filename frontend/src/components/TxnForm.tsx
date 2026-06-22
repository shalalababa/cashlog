import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../api";
import type { Category, Currency, Person, RateInfo, Txn, TxnInput } from "../types";
import ContentAutocomplete from "./ContentAutocomplete";
import AAEditor, { type AAValue } from "./AAEditor";

const EMPTY_AA: AAValue = { payerId: null, splitMode: "equal", members: [], fixed: {}, settled: false };

interface Props {
  currencies: Currency[];
  categories: Category[];
  editing: Txn | null;
  onClose: () => void;
  onSaved: (t: Txn) => void;
}

function today(): string {
  // Local Y-M-D (not toISOString, which is UTC and can be a day off in the evening).
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function TxnForm({ currencies, categories, editing, onClose, onSaved }: Props) {
  const [form, setForm] = useState<TxnInput>(() =>
    editing
      ? {
          date: editing.date,
          direction: editing.direction,
          amount: editing.amount,
          currency: editing.currency,
          content: editing.content,
          category_id: editing.category_id,
          note: editing.note ?? "",
          is_aa: editing.is_aa,
          aa_settled: editing.aa_settled,
        }
      : {
          date: today(),
          direction: "expense",
          amount: "",
          currency: "USD",
          content: "",
          category_id: null,
          note: "",
          is_aa: false,
          aa_settled: false,
        }
  );
  const [rate, setRate] = useState<RateInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [persons, setPersons] = useState<Person[]>([]);
  const [aa, setAA] = useState<AAValue>(EMPTY_AA);

  const set = (patch: Partial<TxnInput>) => setForm((f) => ({ ...f, ...patch }));

  const loadPersons = () => api.persons().then(setPersons).catch(() => setPersons([]));
  useEffect(() => {
    loadPersons();
  }, []);

  // Prefill AA details when editing an existing AA transaction.
  useEffect(() => {
    if (editing?.is_aa) {
      api.getTxnAA(editing.id).then((info) => {
        const anyFixed = info.participants.some((p) => p.fixed_amount != null);
        setAA({
          payerId: info.payer_id,
          splitMode: anyFixed ? "fixed" : "equal",
          members: info.participants.map((p) => p.person_id),
          fixed: Object.fromEntries(info.participants.map((p) => [p.person_id, p.fixed_amount ?? p.owed ?? ""])),
          settled: info.aa_settled,
        });
      });
    }
  }, [editing]);

  // Live rate lookup for the conversion preview.
  useEffect(() => {
    let cancelled = false;
    if (!form.currency || !form.date) return;
    api
      .rate(form.currency, form.date)
      .then((r) => !cancelled && setRate(r))
      .catch(() => !cancelled && setRate(null));
    return () => {
      cancelled = true;
    };
  }, [form.currency, form.date]);

  const baseCcy = currencies.find((c) => c.is_base)?.code ?? "CNY";
  const isBase = form.currency === baseCcy;
  const cats = categories.filter((c) => c.kind === form.direction && c.active);

  let preview = "";
  let stale = false;
  const amt = parseFloat(form.amount);
  if (!isBase && rate?.found && rate.rate && !Number.isNaN(amt)) {
    preview = `≈ ¥${(amt * parseFloat(rate.rate)).toFixed(2)}  (汇率 ${rate.rate} @ ${rate.rate_date})`;
    stale = !!rate.stale;
  } else if (!isBase && rate && !rate.found) {
    preview = "该日期暂无此币种汇率，将先不换算";
  }

  async function submit() {
    setError("");
    if (!form.amount || Number.isNaN(amt)) {
      setError("请输入有效金额");
      return;
    }
    if (form.is_aa) {
      if (aa.members.length === 0) {
        setError("AA 需要至少一名参与人");
        return;
      }
      if (aa.payerId == null) {
        setError("请选择付款人");
        return;
      }
      if (aa.splitMode === "fixed") {
        const sum = aa.members.reduce((s, id) => s + (parseFloat(aa.fixed[id] ?? "") || 0), 0);
        if (Math.abs(sum - amt) > 0.001) {
          setError("自定义分摊合计需与金额相等");
          return;
        }
      }
    }
    setSaving(true);
    try {
      const saved = editing ? await api.updateTxn(editing.id, form) : await api.createTxn(form);
      if (form.is_aa) {
        await api.setTxnAA(saved.id, {
          payer_id: aa.payerId,
          settled: aa.settled,
          participants: aa.members.map((id) => ({
            person_id: id,
            ...(aa.splitMode === "fixed" ? { fixed_amount: aa.fixed[id] ?? "0" } : {}),
          })),
        });
      } else if (editing?.is_aa) {
        await api.clearTxnAA(saved.id);
      }
      onSaved(saved);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={onClose}>
      <motion.div
        className="card modal"
        onMouseDown={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: -16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
      >
        <h3>{editing ? "编辑条目" : "新增条目"}</h3>
        <div className="form-grid">
          <div className="field">
            <label>方向</label>
            <div className="seg">
              <button
                className={form.direction === "expense" ? "active" : ""}
                onClick={() => set({ direction: "expense", category_id: null })}
              >
                支出
              </button>
              <button
                className={form.direction === "income" ? "active" : ""}
                onClick={() => set({ direction: "income", category_id: null, is_aa: false })}
              >
                入账
              </button>
            </div>
          </div>
          <div className="field">
            <label>日期</label>
            <input type="date" value={form.date} onChange={(e) => set({ date: e.target.value })} />
          </div>

          <div className="field">
            <label>金额</label>
            <input
              type="number"
              step="0.01"
              value={form.amount}
              placeholder="0.00"
              onChange={(e) => set({ amount: e.target.value })}
            />
          </div>
          <div className="field">
            <label>币种</label>
            <select value={form.currency} onChange={(e) => set({ currency: e.target.value })}>
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>

          <div className="field full">
            <label>内容</label>
            <ContentAutocomplete
              value={form.content}
              direction={form.direction}
              onChange={(v) => set({ content: v })}
              autoFocus
            />
          </div>

          <div className="field">
            <label>分类</label>
            <select
              value={form.category_id ?? ""}
              onChange={(e) => set({ category_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">未分类</option>
              {cats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>备注</label>
            <input value={form.note ?? ""} onChange={(e) => set({ note: e.target.value })} />
          </div>

          {form.direction === "expense" && (
            <div className="field full">
              <label className="check">
                <input type="checkbox" checked={form.is_aa} onChange={(e) => set({ is_aa: e.target.checked })} />
                这是一笔 AA
              </label>
              {form.is_aa && (
                <AAEditor
                  persons={persons}
                  amount={form.amount}
                  value={aa}
                  onChange={setAA}
                  onPersonsChanged={loadPersons}
                />
              )}
            </div>
          )}

          <div className="field full conv-hint">
            {preview && <span className={stale ? "stale" : ""}>{preview}{stale ? " · 汇率较旧" : ""}</span>}
          </div>
        </div>

        {error && <div style={{ color: "var(--expense)", fontSize: 13, marginTop: 8 }}>{error}</div>}
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>取消</button>
          <button className="btn primary" onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
