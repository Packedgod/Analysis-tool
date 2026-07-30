import { useCallback, useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// Market Pulse user preferences: watchlist, screening standards, and marked
// positions.
//
// These are personal, per-browser research settings with no server-side
// counterpart, so they live in localStorage. Every hook below shares one
// storage event bus so two mounted panels (e.g. the watchlist rail and the
// screener grid) stay in sync without prop-drilling through the page.
// ---------------------------------------------------------------------------

const EVENT = "qa-market-prefs";

function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
  } catch {
    // A corrupt entry must not brick the workspace — fall back and move on.
    return fallback;
  }
}

function writeJSON(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota or private-mode failure: the session still works, it just
    // won't persist. Not worth interrupting research over.
    return;
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { key } }));
}

/** Subscribes to same-tab custom events and cross-tab storage events. */
function usePersisted<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => readJSON(key, fallback));

  useEffect(() => {
    const sync = () => setValue(readJSON(key, fallback));
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
    // `fallback` is a literal at every call site; re-subscribing on identity
    // change would thrash the listener for no behavioural gain.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const update = useCallback((next: T) => {
    writeJSON(key, next);
    setValue(next);
  }, [key]);

  return [value, update] as const;
}

// --- Watchlist -------------------------------------------------------------

const WATCHLIST_KEY = "qa-market-watchlist";
const DEFAULT_WATCHLIST = ["RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "TCS.NS", "INFY.NS"];

export function useWatchlist() {
  const [symbols, setSymbols] = usePersisted<string[]>(WATCHLIST_KEY, DEFAULT_WATCHLIST);

  const add = useCallback((symbol: string) => {
    const clean = symbol.trim().toUpperCase();
    if (!clean) return;
    setSymbols(symbols.includes(clean) ? symbols : [...symbols, clean]);
  }, [symbols, setSymbols]);

  const remove = useCallback((symbol: string) => {
    setSymbols(symbols.filter((s) => s !== symbol));
  }, [symbols, setSymbols]);

  const toggle = useCallback((symbol: string) => {
    const clean = symbol.trim().toUpperCase();
    if (!clean) return;
    setSymbols(symbols.includes(clean) ? symbols.filter((s) => s !== clean) : [...symbols, clean]);
  }, [symbols, setSymbols]);

  const has = useCallback((symbol: string) => symbols.includes(symbol.toUpperCase()), [symbols]);

  return { symbols, add, remove, toggle, has, replace: setSymbols };
}

// --- Screening standards ---------------------------------------------------

export type StandardOperator = "gt" | "lt" | "gte" | "lte";

/** One user-authored screening criterion, e.g. "trailing_pe < 25". */
export interface Standard {
  id: string;
  /** Key on ScreenRow. */
  field: string;
  operator: StandardOperator;
  value: number;
  enabled: boolean;
}

const STANDARDS_KEY = "qa-market-standards";

export function useStandards() {
  const [standards, setStandards] = usePersisted<Standard[]>(STANDARDS_KEY, []);

  const add = useCallback((standard: Omit<Standard, "id">) => {
    setStandards([...standards, { ...standard, id: `std-${Date.now()}-${standards.length}` }]);
  }, [standards, setStandards]);

  const remove = useCallback((id: string) => {
    setStandards(standards.filter((s) => s.id !== id));
  }, [standards, setStandards]);

  const toggle = useCallback((id: string) => {
    setStandards(standards.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s)));
  }, [standards, setStandards]);

  return { standards, add, remove, toggle, replace: setStandards };
}

/** Applies one criterion. A missing value never passes — absent ≠ satisfied. */
export function matchesStandard(value: number | null | undefined, standard: Standard): boolean {
  if (value === null || value === undefined || !Number.isFinite(value)) return false;
  switch (standard.operator) {
    case "gt": return value > standard.value;
    case "lt": return value < standard.value;
    case "gte": return value >= standard.value;
    case "lte": return value <= standard.value;
    default: return false;
  }
}

// --- Marked positions ------------------------------------------------------

export type PositionKind = "entry" | "target" | "stop";

/** A price level the user has marked on a symbol's chart. */
export interface MarkedPosition {
  id: string;
  symbol: string;
  kind: PositionKind;
  price: number;
  note?: string;
}

const POSITIONS_KEY = "qa-market-positions";

export function usePositions(symbol?: string) {
  const [all, setAll] = usePersisted<MarkedPosition[]>(POSITIONS_KEY, []);
  const forSymbol = symbol ? all.filter((p) => p.symbol === symbol) : all;

  const add = useCallback((position: Omit<MarkedPosition, "id">) => {
    setAll([...all, { ...position, id: `pos-${Date.now()}-${all.length}` }]);
  }, [all, setAll]);

  const remove = useCallback((id: string) => {
    setAll(all.filter((p) => p.id !== id));
  }, [all, setAll]);

  return { positions: forSymbol, allPositions: all, add, remove };
}
