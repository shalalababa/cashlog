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

export interface Person {
  id: number;
  name: string;
  initial: string | null;
  is_self: number;
  active: number;
}

export interface Participant {
  person_id: number;
  name?: string | null;
  weight?: string | null;
  fixed_amount?: string | null;
  owed?: string;
  owed_minor?: number;
}

export interface TxnAA {
  txn_id: number;
  is_aa: boolean;
  payer_id: number | null;
  payer: string | null;
  aa_settled: boolean;
  participants: Participant[];
}

export interface UnsettledGroup {
  currency: string;
  minor_unit: number;
  txns: {
    id: number;
    date: string;
    content: string;
    amount: string;
    payer_id: number | null;
    payer: string | null;
    participants: { person_id: number; name: string | null; owed: string }[];
  }[];
}

export interface SettlementGroup {
  currency: string;
  balances: { person_id: number; name: string | null; net: string }[];
  transfers: { from: number; from_name: string | null; to: number; to_name: string | null; amount: string }[];
  txn_ids: number[];
}

export interface Candidate {
  id: number;
  date: string;
  content: string;
  direction: string;
  currency: string;
  amount: string;
}

export interface SessionSummary {
  id: number;
  name: string | null;
  currency: string;
  created_at: string;
}

export interface SessionItem {
  id?: number;
  label: string | null;
  pretax: string;
  shares: { person_id: number; name?: string | null; weight?: string | null }[];
}

export interface Session {
  id: number;
  name: string | null;
  currency: string;
  minor_unit: number;
  payer_id: number | null;
  payer: string | null;
  total_with_tax: string;
  tax_amount: string;
  pretax_total: string;
  items: SessionItem[];
  result: { person_id: number; name: string | null; amount: string }[];
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
