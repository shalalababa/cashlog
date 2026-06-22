import { useEffect, useState } from "react";
import { api } from "../api";
import type { Category, Currency, Person } from "../types";

interface Props {
  categories: Category[];
  currencies: Currency[];
  onChanged: () => void;
}

const PALETTE = ["#FF6B6B", "#4D96FF", "#6BCB77", "#FFD93D", "#9B5DE5", "#00BBF9", "#F15BB5", "#FF9F1C"];

export default function ManageView({ categories, currencies, onChanged }: Props) {
  return (
    <div className="manage-grid">
      <CategorySection kind="expense" title="支出分类" categories={categories} onChanged={onChanged} />
      <div>
        <CategorySection kind="income" title="入账分类" categories={categories} onChanged={onChanged} />
        <div style={{ height: 18 }} />
        <PeopleSection />
        <div style={{ height: 18 }} />
        <CurrencySection currencies={currencies} />
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

function CurrencySection({ currencies }: { currencies: Currency[] }) {
  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-title">币种</div>
      <div className="cat-list">
        {currencies.map((c) => (
          <div className="cat-row" key={c.id}>
            <span className="name">
              {c.name} <span className="muted">({c.code})</span>
            </span>
            {c.is_base === 1 && <span className="badge aa">本位币</span>}
            <span className="grow" />
            <span className="muted">小数位 {c.minor_unit}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
