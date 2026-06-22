import type { Category, Currency, Filters } from "../types";

interface Props {
  filters: Filters;
  categories: Category[];
  currencies: Currency[];
  onChange: (patch: Partial<Filters>) => void;
  onReset: () => void;
}

export default function FiltersBar({ filters, categories, currencies, onChange, onReset }: Props) {
  const cats = categories.filter(
    (c) => filters.direction === "" || c.kind === filters.direction
  );
  return (
    <div className="card filters">
      <div className="seg">
        {[
          ["", "全部"],
          ["expense", "支出"],
          ["income", "入账"],
        ].map(([val, label]) => (
          <button
            key={val}
            className={filters.direction === val ? "active" : ""}
            onClick={() => onChange({ direction: val, category_id: null })}
          >
            {label}
          </button>
        ))}
      </div>

      <input
        className="search"
        placeholder="搜索内容…"
        value={filters.search}
        onChange={(e) => onChange({ search: e.target.value })}
      />

      <select
        value={filters.category_id ?? ""}
        onChange={(e) => onChange({ category_id: e.target.value ? Number(e.target.value) : null })}
      >
        <option value="">全部分类</option>
        {cats.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>

      <select value={filters.currency} onChange={(e) => onChange({ currency: e.target.value })}>
        <option value="">全部币种</option>
        {currencies.map((c) => (
          <option key={c.code} value={c.code}>
            {c.code}
          </option>
        ))}
      </select>

      <input type="date" value={filters.date_from} onChange={(e) => onChange({ date_from: e.target.value })} />
      <span className="muted">–</span>
      <input type="date" value={filters.date_to} onChange={(e) => onChange({ date_to: e.target.value })} />

      <select value={filters.aa} onChange={(e) => onChange({ aa: e.target.value })}>
        <option value="">AA：不限</option>
        <option value="aa">仅 AA</option>
        <option value="unsettled">未结清 AA</option>
      </select>

      <label className="check">
        <input
          type="checkbox"
          checked={filters.uncategorized}
          onChange={(e) => onChange({ uncategorized: e.target.checked })}
        />
        仅未分类
      </label>

      <button className="btn ghost sm" onClick={onReset}>重置</button>
    </div>
  );
}
