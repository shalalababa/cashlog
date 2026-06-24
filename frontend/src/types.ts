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

export interface FiscalMonth {
  period_end: string;
  range_start: string;
  range_end: string;          // inclusive, for chart range calls
  total_cny: number;
  total_usd: number | null;
  credit_card: number;
  credit_card_currency: string | null;
  credit_card_cny: number | null;
  usd_rate: number | null;
  ratio: number | null;
  rate_stale: boolean;
}

export interface CategoryStat {
  category_id: number | null;
  category: string;
  color: string;
  exclude_stats: boolean;
  total: number;
  count: number;
}

export interface CategorySeries {
  category_id: number | null;
  category: string;
  color: string;
  exclude_stats: boolean;
  values: number[];
}

export interface CategoryTrend {
  periods: string[];
  granularity: string;
  series: CategorySeries[];
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

// --- budgets ----------------------------------------------------------------
export interface Budget {
  id: number;
  category_id: number | null;
  amount_type: "absolute" | "percent";
  amount: string | null;       // major CNY (absolute)
  amount_micro: number | null;
  percent: string | null;      // share of overall (percent)
  note: string | null;
  category?: string | null;
  color?: string | null;
}

export interface BudgetList {
  overall: Budget | null;
  categories: Budget[];
}

export interface BudgetProgress {
  limit: string | null;
  limit_micro: number | null;
  actual: string;
  actual_micro: number;
  pct: number | null;          // fraction (actual / limit)
  remaining: string | null;
  over: boolean;
}

export interface OverallStatus extends BudgetProgress {
  budget_id: number | null;
}

export interface CategoryBudgetStatus extends BudgetProgress {
  category_id: number | null;
  category: string | null;
  color: string | null;
  amount_type: "absolute" | "percent";
  percent: string | null;
  budget_id: number;
}

export interface BudgetStatus {
  period_end: string;
  range_start: string;
  range_end: string;
  has_overall: boolean;
  overall: OverallStatus;
  categories: CategoryBudgetStatus[];
}

export interface BudgetInput {
  category_id: number | null;
  amount_type?: "absolute" | "percent";
  amount?: string | null;
  percent?: string | null;
  note?: string | null;
}

// --- dashboard --------------------------------------------------------------
export interface MonthSummary {
  period_end: string;
  range_start: string;
  range_end: string;
  total_micro: number;
  total_cny: number;
  delta?: number;
  delta_pct?: number | null;
}

export interface AAUnsettledSummary {
  count: number;
  by_currency: { currency: string; count: number; amount: string }[];
}

export interface Dashboard {
  today: string;
  current: MonthSummary;
  previous: MonthSummary;
  top_categories: CategoryStat[];
  budget: BudgetStatus;
  aa_unsettled: AAUnsettledSummary;
}
