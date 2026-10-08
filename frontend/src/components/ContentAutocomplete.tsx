import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Suggestion } from "../types";

interface Props {
  value: string;
  direction: "expense" | "income";
  onChange: (v: string) => void;
  /** Fired when the user accepts a suggestion (dropdown, Enter, or ghost Tab/→). */
  onPick?: (s: Suggestion) => void;
  autoFocus?: boolean;
}

/**
 * Excel-style content autocomplete.
 * - typing fetches prefix suggestions (most-used first) shown in a dropdown
 * - when exactly one suggestion remains, its tail is shown inline as ghost text;
 *   Tab / → / Enter completes it
 */
export default function ContentAutocomplete({ value, direction, onChange, onPick, autoFocus }: Props) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number>();
  const seq = useRef(0);   // drop responses overtaken by newer typing / a pick

  useEffect(() => {
    window.clearTimeout(timer.current);
    const prefix = value.trim();
    if (!prefix) {
      setSuggestions([]);
      return;
    }
    const mine = ++seq.current;
    timer.current = window.setTimeout(async () => {
      try {
        const list = await api.autocomplete(direction, prefix);
        if (mine !== seq.current) return;
        // Drop an exact-match-only result (nothing left to suggest).
        const filtered = list.filter((s) => s.content !== value);
        setSuggestions(filtered);
        setActive(0);
        setOpen(filtered.length > 0);
      } catch {
        setSuggestions([]);
      }
    }, 120);
    return () => window.clearTimeout(timer.current);
  }, [value, direction]);

  // Inline ghost only when a single candidate starts with what's typed.
  const ghost =
    suggestions.length === 1 && suggestions[0].content.startsWith(value) && value
      ? suggestions[0].content.slice(value.length)
      : "";

  function complete(s: Suggestion) {
    seq.current++;   // a still-pending fetch must not reopen the dropdown
    onChange(s.content);
    onPick?.(s);
    setSuggestions([]);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (ghost && (e.key === "Tab" || e.key === "ArrowRight")) {
      if (e.key === "Tab") e.preventDefault();
      complete(suggestions[0]);
      return;
    }
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      if (suggestions[active]) {
        e.preventDefault();
        complete(suggestions[active]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="ac">
      <div className="ac-ghost" aria-hidden>
        <span className="typed">{value}</span>
        <span className="rest">{ghost}</span>
      </div>
      <input
        ref={inputRef}
        className="ac-input"
        value={value}
        autoFocus={autoFocus}
        placeholder="消费内容 / 入账来源"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(suggestions.length > 0)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      />
      {open && (
        <div className="ac-pop">
          {suggestions.map((s, i) => (
            <div
              key={s.content}
              className={"ac-item" + (i === active ? " active" : "")}
              onMouseDown={(e) => {
                e.preventDefault();
                complete(s);
              }}
            >
              <span>{s.content}</span>
              <span className="freq">{s.freq}×</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
