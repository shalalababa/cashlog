import { useEffect, useState } from "react";
import { api } from "../api";
import type { Candidate, Category, Currency, Person, ReceiptTxn, Session, SessionItem, SettlementGroup, UnsettledGroup } from "../types";

interface Props {
  currencies: Currency[];
  categories: Category[];
  notify: (msg: string, error?: boolean) => void;
  /** Called after an action creates or changes transactions, so the ledger can refetch. */
  onTxnsChanged: () => void;
}

export default function AAView({ currencies, categories, notify, onTxnsChanged }: Props) {
  const [tab, setTab] = useState<"settle" | "calc" | "receipts" | "cands">("settle");
  const [persons, setPersons] = useState<Person[]>([]);
  const loadPersons = () => api.persons().then(setPersons).catch(() => setPersons([]));
  useEffect(() => {
    loadPersons();
  }, []);

  return (
    <div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={`tab ${tab === "settle" ? "active" : ""}`} onClick={() => setTab("settle")}>未结清 / 转账</button>
        <button className={`tab ${tab === "calc" ? "active" : ""}`} onClick={() => setTab("calc")}>小票计算器</button>
        <button className={`tab ${tab === "receipts" ? "active" : ""}`} onClick={() => setTab("receipts")}>小票细项</button>
        <button className={`tab ${tab === "cands" ? "active" : ""}`} onClick={() => setTab("cands")}>历史候选</button>
      </div>
      {tab === "settle" && <SettlementPanel notify={notify} onTxnsChanged={onTxnsChanged} />}
      {tab === "calc" && <CalculatorPanel persons={persons} currencies={currencies} categories={categories} onPersonsChanged={loadPersons} notify={notify} onTxnsChanged={onTxnsChanged} />}
      {tab === "receipts" && <ReceiptsPanel notify={notify} />}
      {tab === "cands" && <CandidatesPanel persons={persons} notify={notify} onTxnsChanged={onTxnsChanged} />}
    </div>
  );
}

/* ---------------- Settlement ---------------- */
function SettlementPanel({ notify, onTxnsChanged }: { notify: (m: string, e?: boolean) => void; onTxnsChanged: () => void }) {
  const [groups, setGroups] = useState<UnsettledGroup[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<SettlementGroup[] | null>(null);

  const load = () => api.unsettled().then((g) => { setGroups(g); setResult(null); }).catch((e) => notify(e.message, true));
  useEffect(() => {
    load();
  }, []);

  const allIds = groups.flatMap((g) => g.txns.map((t) => t.id));
  const targetIds = selected.size ? [...selected] : allIds;

  function toggle(id: number) {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  }

  async function compute() {
    try {
      setResult(await api.settlement(selected.size ? targetIds : undefined));
    } catch (e) {
      notify((e as Error).message, true);
    }
  }
  async function settle(ids: number[]) {
    if (!ids.length) return;
    if (!confirm(`将 ${ids.length} 笔标记为已结清？`)) return;
    try {
      await api.settle(ids);
      notify("已标记结清");
      setSelected(new Set());
      load();
      onTxnsChanged();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  if (groups.length === 0) return <div className="card"><div className="empty">没有未结清的 AA 条目 🎉</div></div>;

  return (
    <div>
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        {groups.map((g) => (
          <div key={g.currency} style={{ marginBottom: 14 }}>
            <div className="section-title">{g.currency}（原币种）</div>
            {g.txns.map((t) => (
              <label key={t.id} className="aa-txn">
                <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                <span className="muted">{t.date}</span>
                <span className="grow2">{t.content || "—"}</span>
                <span className="muted">付：{t.payer ?? "?"}</span>
                <span className="amount expense">{t.amount} {g.currency}</span>
              </label>
            ))}
          </div>
        ))}
        <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
          <button className="btn primary" onClick={compute}>
            计算最优转账{selected.size ? `（选中 ${selected.size} 笔）` : "（全部）"}
          </button>
          <button className="btn" onClick={() => settle(targetIds)}>标记选中/全部为已结清</button>
        </div>
      </div>

      {result && result.map((r) => (
        <div key={r.currency} className="card" style={{ padding: 16, marginBottom: 12 }}>
          <div className="section-title">{r.currency} · 最优转账方案</div>
          {r.transfers.length === 0 ? (
            <div className="muted">已平衡，无需转账。</div>
          ) : (
            <div className="transfers">
              {r.transfers.map((t, i) => (
                <div className="transfer" key={i}>
                  <span className="from">{t.from_name}</span>
                  <span className="arrow">→</span>
                  <span className="to">{t.to_name}</span>
                  <span className="amt">{t.amount} {r.currency}</span>
                </div>
              ))}
            </div>
          )}
          <div className="balances">
            {r.balances.map((b) => (
              <span key={b.person_id} className={"bal " + (parseFloat(b.net) >= 0 ? "pos" : "neg")}>
                {b.name} {parseFloat(b.net) >= 0 ? "+" : ""}{b.net}
              </span>
            ))}
          </div>
          <button className="btn sm" style={{ marginTop: 10 }} onClick={() => settle(r.txn_ids)}>标记本币种为已结清</button>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Receipt calculator ---------------- */
interface DraftItem { label: string; pretax: string; members: number[]; }

function CalculatorPanel({ persons, currencies, categories, onPersonsChanged, notify, onTxnsChanged }: {
  persons: Person[]; currencies: Currency[]; categories: Category[]; onPersonsChanged: () => void;
  notify: (m: string, e?: boolean) => void; onTxnsChanged: () => void;
}) {
  const [currency, setCurrency] = useState("USD");
  const [payerId, setPayerId] = useState<number | null>(null);
  const [total, setTotal] = useState("");
  const [items, setItems] = useState<DraftItem[]>([{ label: "", pretax: "", members: [] }]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [result, setResult] = useState<{ person_id: number; name: string | null; amount: string }[] | null>(null);
  // Set once this receipt produced a txn; the saved receipt is then frozen, so a
  // further 计算 starts a new one instead of editing the generated history.
  const [generated, setGenerated] = useState(false);
  const [newName, setNewName] = useState("");
  const active = persons.filter((p) => p.active);

  function setItem(i: number, patch: Partial<DraftItem>) {
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  }
  function toggleMember(i: number, id: number) {
    const it = items[i];
    setItem(i, { members: it.members.includes(id) ? it.members.filter((m) => m !== id) : [...it.members, id] });
  }
  async function addPerson() {
    if (!newName.trim()) return;
    try { await api.createPerson(newName.trim()); setNewName(""); onPersonsChanged(); } catch { /* dup */ }
  }

  async function calc() {
    try {
      const payload = {
        id: sessionId, name: "小票", currency, payer_id: payerId, total_with_tax: total || "0",
        items: items.filter((it) => it.pretax).map((it) => ({ label: it.label, pretax: it.pretax, person_ids: it.members })),
      };
      const s = await api.saveSession(payload);
      setSessionId(s.id);
      setResult(s.result);
      setGenerated(false);
    } catch (e) {
      notify((e as Error).message, true);
    }
  }
  async function generate() {
    if (!sessionId) { notify("请先计算", true); return; }
    if (payerId == null) { notify("请先选择付款人", true); return; }
    const expenseCats = categories.filter((c) => c.kind === "expense");
    try {
      await api.generateTxn(sessionId, {
        date: new Date().toLocaleDateString("sv"), content: "小票 AA", category_id: expenseCats[0]?.id ?? null,
      });
      notify("已生成 AA 交易，小项明细可在「小票细项」查看");
      setSessionId(null);
      setGenerated(true);
      onTxnsChanged();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="section-title">小票计算器（税费按税前金额比例分摊）</div>
      <div className="calc-head">
        <label className="field"><span>币种</span>
          <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
          </select>
        </label>
        <label className="field"><span>含税总价</span>
          <input type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} />
        </label>
        <label className="field"><span>付款人</span>
          <select value={payerId ?? ""} onChange={(e) => setPayerId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">（无）</option>
            {active.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="field"><span>新建参与人</span>
          <div style={{ display: "flex", gap: 6 }}>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addPerson()} />
            <button className="btn sm" onClick={addPerson}>+</button>
          </div>
        </div>
      </div>

      <table className="calc-items">
        <thead><tr><th>小项</th><th>税前</th><th>分摊给</th><th></th></tr></thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td><input placeholder="名称" value={it.label} onChange={(e) => setItem(i, { label: e.target.value })} /></td>
              <td><input type="number" step="0.01" placeholder="0.00" value={it.pretax} onChange={(e) => setItem(i, { pretax: e.target.value })} /></td>
              <td>
                <div className="chips-pick">
                  {active.map((p) => (
                    <button key={p.id} type="button" className={"pick" + (it.members.includes(p.id) ? " on" : "")} onClick={() => toggleMember(i, p.id)}>{p.name}</button>
                  ))}
                </div>
              </td>
              <td><button className="btn sm ghost danger" onClick={() => setItems(items.filter((_, idx) => idx !== i))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn sm" onClick={() => setItems([...items, { label: "", pretax: "", members: [] }])}>+ 添加小项</button>

      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn primary" onClick={calc}>计算</button>
        <button className="btn" onClick={generate} disabled={!result || payerId == null || generated}
                title={generated ? "已生成；修改后重新计算可生成新的一笔" : payerId == null ? "请先选择付款人" : undefined}>
          {generated ? "已生成" : "生成 AA 交易"}
        </button>
        {result && payerId == null && <span className="muted" style={{ alignSelf: "center" }}>选择付款人后可生成交易</span>}
      </div>

      {result && (
        <div className="calc-result">
          {result.map((r) => (
            <div key={r.person_id} className="res-cell"><span>{r.name}</span><b>{r.amount} {currency}</b></div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- Receipt history (小票细项) ---------------- */
function ReceiptsPanel({ notify }: { notify: (m: string, e?: boolean) => void }) {
  const [list, setList] = useState<ReceiptTxn[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selId, setSelId] = useState<number | null>(null);   // session id
  const [detail, setDetail] = useState<Session | null>(null);

  useEffect(() => {
    api.receipts()
      .then((r) => { setList(r); setLoaded(true); if (r.length) setSelId(r[0].session_id); })
      .catch((e) => { notify(e.message, true); setLoaded(true); });
  }, []);
  useEffect(() => {
    if (selId == null) { setDetail(null); return; }
    let live = true;
    api.getSession(selId).then((s) => live && setDetail(s)).catch((e) => notify(e.message, true));
    return () => { live = false; };
  }, [selId]);

  if (loaded && !list.length) {
    return (
      <div className="card empty" style={{ padding: 24 }}>
        还没有由小票计算器生成的 AA 交易。在「小票计算器」里计算并生成交易后，小项与分摊明细会保存在这里。
      </div>
    );
  }
  const sel = list.find((r) => r.session_id === selId);
  return (
    <div className="receipts">
      <div className="card receipts-list">
        {list.map((r) => (
          <button key={r.session_id} className={"receipt-row" + (r.session_id === selId ? " active" : "")}
                  onClick={() => setSelId(r.session_id)}>
            <span className="muted">{r.date}</span>
            <span className="receipt-name">{r.content || "（无内容）"}</span>
            <span className="receipt-meta">
              <b>{r.amount} {r.currency}</b>
              <span className="muted"> · {r.item_count} 项</span>
              {r.aa_settled && <span className="badge aa" style={{ marginLeft: 6 }}>AA✓</span>}
            </span>
          </button>
        ))}
      </div>

      <div className="card" style={{ padding: 18 }}>
        {!detail || !sel ? <div className="muted">加载中…</div> : (
          <>
            <div className="section-title">{sel.content || "小票"} <span className="muted">· {sel.date}</span></div>
            <div className="receipt-sum">
              <span>含税总价 <b>{detail.total_with_tax} {detail.currency}</b></span>
              <span>税前合计 <b>{detail.pretax_total}</b></span>
              <span>税费 <b>{detail.tax_amount}</b></span>
              <span>付款人 <b>{detail.payer ?? "—"}</b></span>
            </div>

            <table className="calc-items receipt-items">
              <thead><tr><th>小项</th><th className="num">税前</th><th className="num">含税</th><th>分摊（含税）</th></tr></thead>
              <tbody>
                {detail.items.map((it, i) => (
                  <tr key={it.id ?? i}>
                    <td>{it.label?.trim() ? it.label : <span className="muted">小项 {i + 1}</span>}</td>
                    <td className="num">{it.pretax}</td>
                    <td className="num">{it.with_tax ?? "—"}</td>
                    <td>
                      {(it.per_person ?? []).length ? (
                        <div className="chips-pick">
                          {it.per_person!.map((p) => (
                            <span key={p.person_id} className="pick on" title={`税前 ${p.pretax}`}>
                              {p.name ?? `#${p.person_id}`} {p.with_tax}
                            </span>
                          ))}
                        </div>
                      ) : <span className="muted">未分摊</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="section-title" style={{ marginTop: 16 }}>每人合计</div>
            <div className="calc-result">
              {detail.result.map((r) => (
                <div key={r.person_id} className="res-cell">
                  <span>{r.name}</span>
                  <b>{r.amount} {detail.currency}</b>
                  {r.pretax && <span className="muted" style={{ fontSize: 11 }}>税前 {r.pretax}</span>}
                </div>
              ))}
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
              每人合计是生成交易时的应付金额（精确到分）；单项含税金额按税前比例分摊税费，仅供参考，可能有 ±0.01 的取整差。
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- Candidates ---------------- */
function CandidatesPanel({ persons, notify, onTxnsChanged }: {
  persons: Person[]; notify: (m: string, e?: boolean) => void; onTxnsChanged: () => void;
}) {
  const [cands, setCands] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [payerId, setPayerId] = useState<number | null>(null);
  const [members, setMembers] = useState<number[]>([]);
  const active = persons.filter((p) => p.active);

  const load = () => api.candidates().then(setCands).catch((e) => notify(e.message, true));
  useEffect(() => {
    load();
  }, []);

  function toggle(id: number) {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  }
  function toggleMember(id: number) {
    setMembers((m) => (m.includes(id) ? m.filter((x) => x !== id) : [...m, id]));
  }
  async function structure() {
    if (!selected.size || !members.length || payerId == null) {
      notify("请选择条目、付款人和参与人", true);
      return;
    }
    try {
      const { structured } = await api.structure({ txn_ids: [...selected], payer_id: payerId, participant_ids: members });
      notify(`已结构化 ${structured} 笔（平均分摊）`);
      setSelected(new Set());
      load();
      onTxnsChanged();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }

  if (cands.length === 0) return <div className="card"><div className="empty">没有待结构化的 AA 候选</div></div>;

  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="section-title">消费内容含「AA」、尚未结构化（{cands.length} 笔）</div>
      <div style={{ maxHeight: 320, overflowY: "auto", margin: "8px 0" }}>
        {cands.map((c) => (
          <label key={c.id} className="aa-txn">
            <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
            <span className="muted">{c.date}</span>
            <span className="grow2">{c.content}</span>
            <span className="amount expense">{c.amount} {c.currency}</span>
          </label>
        ))}
      </div>
      <div className="cand-controls">
        <div>
          <span className="muted">付款人：</span>
          <select value={payerId ?? ""} onChange={(e) => setPayerId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">选择</option>
            {active.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="chips-pick">
          <span className="muted" style={{ marginRight: 4 }}>参与人：</span>
          {active.map((p) => (
            <button key={p.id} type="button" className={"pick" + (members.includes(p.id) ? " on" : "")} onClick={() => toggleMember(p.id)}>{p.name}</button>
          ))}
        </div>
        <button className="btn primary" onClick={structure}>批量结构化（平均，选中 {selected.size}）</button>
      </div>
    </div>
  );
}
