import type { Category, Meta, RateInfo, Suggestion, Txn, TxnInput, TxnPage } from "./types";

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
};
