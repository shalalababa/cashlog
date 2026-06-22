import { useState } from "react";
import { api } from "../api";
import type { Person } from "../types";

export interface AAValue {
  payerId: number | null;
  splitMode: "equal" | "fixed";
  members: number[];                       // participant person ids
  fixed: Record<number, string>;           // person_id -> fixed amount (major)
  settled: boolean;
}

interface Props {
  persons: Person[];
  amount: string;
  value: AAValue;
  onChange: (v: AAValue) => void;
  onPersonsChanged: () => void;
}

export default function AAEditor({ persons, amount, value, onChange, onPersonsChanged }: Props) {
  const [newName, setNewName] = useState("");
  const active = persons.filter((p) => p.active);

  const set = (patch: Partial<AAValue>) => onChange({ ...value, ...patch });

  function toggle(id: number) {
    const members = value.members.includes(id)
      ? value.members.filter((m) => m !== id)
      : [...value.members, id];
    const payerId = members.includes(value.payerId ?? -1) ? value.payerId : (members[0] ?? null);
    set({ members, payerId });
  }

  async function addPerson() {
    const name = newName.trim();
    if (!name) return;
    try {
      const p = await api.createPerson(name);
      setNewName("");
      onPersonsChanged();
      set({ members: [...value.members, p.id], payerId: value.payerId ?? p.id });
    } catch {
      /* duplicate name etc. */
    }
  }

  const amt = parseFloat(amount) || 0;
  const fixedSum = value.members.reduce((s, id) => s + (parseFloat(value.fixed[id] ?? "") || 0), 0);
  const equalEach = value.members.length ? (amt / value.members.length).toFixed(2) : "0";

  return (
    <div className="aa-editor">
      <div className="aa-row">
        <span className="muted">参与人</span>
        <div className="chips-pick">
          {active.map((p) => (
            <button
              key={p.id}
              type="button"
              className={"pick" + (value.members.includes(p.id) ? " on" : "")}
              onClick={() => toggle(p.id)}
            >
              {p.name}
            </button>
          ))}
          <input
            className="add-person"
            placeholder="+ 新建"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPerson())}
          />
        </div>
      </div>

      {value.members.length > 0 && (
        <>
          <div className="aa-row">
            <span className="muted">付款人</span>
            <select value={value.payerId ?? ""} onChange={(e) => set({ payerId: e.target.value ? Number(e.target.value) : null })}>
              {value.members.map((id) => {
                const p = persons.find((x) => x.id === id);
                return <option key={id} value={id}>{p?.name}</option>;
              })}
            </select>
            <div className="seg" style={{ marginLeft: "auto" }}>
              <button type="button" className={value.splitMode === "equal" ? "active" : ""} onClick={() => set({ splitMode: "equal" })}>平均</button>
              <button type="button" className={value.splitMode === "fixed" ? "active" : ""} onClick={() => set({ splitMode: "fixed" })}>自定义</button>
            </div>
          </div>

          {value.splitMode === "equal" ? (
            <div className="conv-hint">每人 ≈ {equalEach}</div>
          ) : (
            <div className="fixed-grid">
              {value.members.map((id) => {
                const p = persons.find((x) => x.id === id);
                return (
                  <label key={id} className="fixed-cell">
                    <span>{p?.name}</span>
                    <input
                      type="number"
                      step="0.01"
                      value={value.fixed[id] ?? ""}
                      onChange={(e) => set({ fixed: { ...value.fixed, [id]: e.target.value } })}
                    />
                  </label>
                );
              })}
              <div className={"conv-hint" + (Math.abs(fixedSum - amt) > 0.001 ? " mismatch" : "")}>
                合计 {fixedSum.toFixed(2)} / {amt.toFixed(2)}
                {Math.abs(fixedSum - amt) > 0.001 && " · 需与金额相等"}
              </div>
            </div>
          )}

          <label className="check" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={value.settled} onChange={(e) => set({ settled: e.target.checked })} />
            已结清
          </label>
        </>
      )}
    </div>
  );
}
