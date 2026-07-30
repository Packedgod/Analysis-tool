import { abbreviateNum } from "@/lib/formatters";
import type { ScreenRow } from "@/lib/api";

// ---------------------------------------------------------------------------
// Field metadata for the screener, comparison table, and standards editor.
//
// One declaration per metric drives all three surfaces, so a column, a filter
// operand, and a comparison row can never drift apart in label or units.
// ---------------------------------------------------------------------------

export type FieldFormat = "price" | "percent" | "percentPlain" | "ratio" | "currency" | "integer" | "percent01";

export interface FieldSpec {
  /** Key on ScreenRow. */
  key: keyof ScreenRow;
  label: string;
  format: FieldFormat;
  /** Whether a larger value is generally the more favourable reading. Used only
   *  to tint comparison cells; deliberately absent where it is ambiguous. */
  better?: "higher" | "lower";
  group: "Price" | "Valuation" | "Quality" | "Risk" | "Scale";
}

export const FIELD_SPECS: FieldSpec[] = [
  { key: "price", label: "Price", format: "price", group: "Price" },
  { key: "change_percent", label: "Change %", format: "percent", better: "higher", group: "Price" },
  { key: "fifty_two_week_high", label: "52W High", format: "price", group: "Price" },
  { key: "fifty_two_week_low", label: "52W Low", format: "price", group: "Price" },
  { key: "market_cap", label: "Market Cap", format: "currency", group: "Scale" },
  { key: "average_volume", label: "Avg Volume", format: "integer", group: "Scale" },
  { key: "trailing_pe", label: "P/E (TTM)", format: "ratio", better: "lower", group: "Valuation" },
  { key: "forward_pe", label: "P/E (Fwd)", format: "ratio", better: "lower", group: "Valuation" },
  { key: "price_to_book", label: "P/B", format: "ratio", better: "lower", group: "Valuation" },
  { key: "dividend_yield", label: "Div Yield", format: "percentPlain", better: "higher", group: "Valuation" },
  { key: "return_on_equity", label: "ROE", format: "percent01", better: "higher", group: "Quality" },
  { key: "profit_margins", label: "Net Margin", format: "percent01", better: "higher", group: "Quality" },
  { key: "revenue_growth", label: "Rev Growth", format: "percent01", better: "higher", group: "Quality" },
  { key: "debt_to_equity", label: "Debt/Equity", format: "ratio", better: "lower", group: "Risk" },
  { key: "beta", label: "Beta", format: "ratio", group: "Risk" },
];

export const FIELD_BY_KEY = new Map(FIELD_SPECS.map((spec) => [spec.key as string, spec]));

/**
 * Formats a metric for display. Returns an em dash for absent values —
 * a missing fundamental is shown as missing, never as zero.
 */
export function formatField(value: number | null | undefined, format: FieldFormat, currency?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  switch (format) {
    case "price":
      return `${currencySymbol(currency)}${value.toLocaleString(undefined, {
        minimumFractionDigits: value >= 1000 ? 0 : 2,
        maximumFractionDigits: value >= 1000 ? 0 : 2,
      })}`;
    // Signed: a price move reads better with an explicit direction.
    case "percent":
      return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
    // Unsigned: a yield or ratio is a level, not a change — "+0.45%" misreads
    // as a gain rather than the yield itself.
    case "percentPlain":
      return `${value.toFixed(2)}%`;
    // yfinance reports ratios such as ROE and margins as fractions (0.21 = 21%).
    case "percent01":
      return `${(value * 100).toFixed(1)}%`;
    case "ratio":
      return value.toFixed(2);
    case "currency":
      return `${currencySymbol(currency)}${abbreviateNum(value)}`;
    case "integer":
      return abbreviateNum(value);
    default:
      return String(value);
  }
}

export function currencySymbol(currency?: string | null): string {
  switch ((currency || "").toUpperCase()) {
    case "INR": return "₹";
    case "USD": return "$";
    case "EUR": return "€";
    case "GBP": return "£";
    case "JPY": return "¥";
    case "": return "";
    default: return "";
  }
}

/** Where the last price sits within the 52-week range, as 0..1. */
export function rangePosition(row: Pick<ScreenRow, "price" | "fifty_two_week_high" | "fifty_two_week_low">): number | null {
  const { price, fifty_two_week_high: high, fifty_two_week_low: low } = row;
  if (price == null || high == null || low == null) return null;
  const span = high - low;
  if (!Number.isFinite(span) || span <= 0) return null;
  return Math.min(1, Math.max(0, (price - low) / span));
}
