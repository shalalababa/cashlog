import type {
  Budget,
  BudgetInput,
  BudgetList,
  BudgetStatus,
  Candidate,
  Category,
  CategoryStat,
  CategoryTrend,
  Dashboard,
  FiscalMonth,
  Meta,
  Participant,
  Person,
  RateInfo,
  RateRefreshResult,
  RateStatus,
  Session,
  SessionSummary,
  SettlementGroup,
  Suggestion,
  Txn,
  TxnAA,
  TxnInput,
  TxnPage,
  UnsettledGroup,
  XlsxDiffResult,
  XlsxExportResult,
  XlsxImportResult,
} from "./types";

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => req<Meta>("/api/meta"),

  txns: (params: Record<string, string | number | boolean | null>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== null && v !== "" && v !== undefined) qs.set(k, String(v));
    }
    return req<TxnPage>(`/api/txns?${qs.toString()}`);
  },

  createTxn: (body: TxnInput) =>
    req<Txn>("/api/txns", { method: "POST", body: JSON.stringify(body) }),

  updateTxn: (id: number, body: TxnInput) =>
    req<Txn>(`/api/txns/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  deleteTxn: (id: number) => req<void>(`/api/txns/${id}`, { method: "DELETE" }),

  autocomplete: (direction: string, prefix: string) =>
    req<Suggestion[]>(
      `/api/autocomplete?direction=${direction}&prefix=${encodeURIComponent(prefix)}`
    ),

  rate: (currency: string, date: string) =>
    req<RateInfo>(`/api/rate?currency=${currency}&date=${date}`),

  createCategory: (body: Partial<Category>) =>
    req<Category>("/api/categories", { method: "POST", body: JSON.stringify(body) }),

  updateCategory: (id: number, body: Partial<Category>) =>
    req<Category>(`/api/categories/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  // --- AA: people ---
  persons: () => req<Person[]>("/api/persons"),
  createPerson: (name: string, initial?: string) =>
    req<Person>("/api/persons", { method: "POST", body: JSON.stringify({ name, initial }) }),
  updatePerson: (id: number, body: Partial<Person>) =>
    req<Person>(`/api/persons/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  // --- AA: per-transaction ---
  getTxnAA: (id: number) => req<TxnAA>(`/api/txns/${id}/aa`),
  setTxnAA: (id: number, body: { payer_id: number | null; participants: Participant[]; settled: boolean }) =>
    req<TxnAA>(`/api/txns/${id}/aa`, { method: "PUT", body: JSON.stringify(body) }),
  clearTxnAA: (id: number) => req<TxnAA>(`/api/txns/${id}/aa`, { method: "DELETE" }),

  // --- AA: settlement ---
  unsettled: () => req<UnsettledGroup[]>("/api/aa/unsettled"),
  settlement: (txn_ids?: number[]) =>
    req<SettlementGroup[]>("/api/aa/settlement", { method: "POST", body: JSON.stringify({ txn_ids: txn_ids ?? null }) }),
  settle: (txn_ids: number[]) =>
    req<{ settled: number }>("/api/aa/settle", { method: "POST", body: JSON.stringify({ txn_ids }) }),

  // --- AA: candidates ---
  candidates: () => req<Candidate[]>("/api/aa/candidates"),
  structure: (body: { txn_ids: number[]; payer_id: number; participant_ids: number[]; settled?: boolean }) =>
    req<{ structured: number }>("/api/aa/structure", { method: "POST", body: JSON.stringify(body) }),

  // --- AA: calculator ---
  sessions: () => req<SessionSummary[]>("/api/aa/sessions"),
  getSession: (id: number) => req<Session>(`/api/aa/sessions/${id}`),
  saveSession: (body: any) =>
    body.id
      ? req<Session>(`/api/aa/sessions/${body.id}`, { method: "PUT", body: JSON.stringify(body) })
      : req<Session>("/api/aa/sessions", { method: "POST", body: JSON.stringify(body) }),
  deleteSession: (id: number) => req<void>(`/api/aa/sessions/${id}`, { method: "DELETE" }),
  generateTxn: (id: number, body: { date: string; content: string; category_id: number | null }) =>
    req<Txn>(`/api/aa/sessions/${id}/generate`, { method: "POST", body: JSON.stringify(body) }),

  // --- stats ---
  fiscal: () => req<FiscalMonth[]>("/api/stats/fiscal"),
  categoryBreakdown: (date_from: string, date_to: string) =>
    req<CategoryStat[]>(`/api/stats/categories?date_from=${date_from}&date_to=${date_to}`),
  categoryTrend: (date_from: string, date_to: string, granularity: string) =>
    req<CategoryTrend>(
      `/api/stats/category-trend?date_from=${date_from}&date_to=${date_to}&granularity=${granularity}`
    ),

  // --- budgets + dashboard ---
  budgets: () => req<BudgetList>("/api/budgets"),
  budgetStatus: (period_end?: string) =>
    req<BudgetStatus>(`/api/budgets/status${period_end ? `?period_end=${period_end}` : ""}`),
  setBudget: (body: BudgetInput) =>
    req<Budget>("/api/budgets", { method: "PUT", body: JSON.stringify(body) }),
  deleteBudget: (id: number) => req<void>(`/api/budgets/${id}`, { method: "DELETE" }),
  dashboard: () => req<Dashboard>("/api/dashboard"),

  // --- exchange rates ---
  rateStatus: () => req<RateStatus>("/api/rates/status"),
  refreshRates: (body: { currencies?: string[]; start_date?: string; end_date?: string } = {}) =>
    req<RateRefreshResult>("/api/rates/refresh", { method: "POST", body: JSON.stringify(body) }),

  // --- xlsx sync ---
  xlsxDiff: () => req<XlsxDiffResult>("/api/xlsx/diff"),
  xlsxExport: () => req<XlsxExportResult>("/api/xlsx/export", { method: "POST" }),
  xlsxImport: (body: { apply_deletions?: boolean; apply_conflicts?: boolean } = {}) =>
    req<XlsxImportResult>("/api/xlsx/import", { method: "POST", body: JSON.stringify(body) }),
};
