export interface Txn {
  id: number;
  external_uid: string;
  date: string;
  direction: "expense" | "income";
  amount: string;
  currency: string;
  currency_name: string;
  content: string;
  category_id: number | null;
  category: string | null;
  category_color: string | null;
  note: string | null;
  is_aa: boolean;
  payer_id: number | null;
  aa_settled: boolean;
  base_cny: string | null;
  rate_used: string | null;
  rate_date_used: string | null;
  rate_stale_days: number;
  rate_stale: boolean;
  has_rate: boolean;
  revision: number;
}

export interface Currency {
  id: number;
  code: string;
  name: string;
  symbol: string | null;
  minor_unit: number;
  is_base: number;
  active: number;
}

export interface Category {
  id: number;
  name: string;
  kind: "expense" | "income";
  color: string | null;
  icon: string | null;
  exclude_stats: number;
  sort_order: number;
  active: number;
}

export interface Meta {
  currencies: Currency[];
  categories: Category[];
  settings: Record<string, string>;
}

export interface TxnPage {
  items: Txn[];
  total: number;
  limit: number;
  offset: number;
}

export interface RateInfo {
  found: boolean;
  currency: string;
  date: string;
  rate?: string;
  rate_date?: string;
  stale_days?: number;
  stale?: boolean;
}

export interface Suggestion {
  content: string;
  freq: number;
  last_used: string;
}

export interface TxnInput {
  date: string;
  direction: "expense" | "income";
  amount: string;
  currency: string;
  content: string;
  category_id: number | null;
  note: string | null;
  is_aa: boolean;
  aa_settled: boolean;
}

export interface Filters {
  direction: string;
  search: string;
  category_id: number | null;
  currency: string;
  date_from: string;
  date_to: string;
  aa: string;
  uncategorized: boolean;
}
