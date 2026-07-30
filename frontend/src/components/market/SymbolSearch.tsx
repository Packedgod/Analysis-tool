import { useEffect, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";
import { api, type SymbolSearchResult } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  onSelect: (symbol: string) => void;
  placeholder?: string;
}

/**
 * Debounced symbol lookup with a keyboard-navigable result list.
 *
 * Requests are debounced *and* abortable: without the abort, a slow early
 * response can land after a faster later one and repopulate the list with
 * results for a query the user has already moved on from.
 */
export function SymbolSearch({ onSelect, placeholder = "Search any listed company or ticker…" }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      api.searchSymbols(term, controller.signal)
        .then((response) => {
          setResults(response.results);
          setCursor(0);
          setError(response.results.length ? null : "No matching securities.");
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setResults([]);
          setError(err instanceof Error ? err.message : "Search unavailable.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 280);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const choose = (symbol: string) => {
    onSelect(symbol);
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open || !results.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => (c + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => (c - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(results[cursor].symbol);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={boxRef} className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute start-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={query}
          onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label="Search securities"
          className="stock-input ps-10 pe-10"
        />
        {loading && <Loader2 className="absolute end-3.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-primary" />}
        {!loading && query && (
          <button
            type="button"
            onClick={() => { setQuery(""); setResults([]); }}
            className="absolute end-3 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition hover:text-foreground"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && query.trim().length >= 2 && (results.length > 0 || error) && (
        <ul
          className="absolute z-50 mt-2 max-h-80 w-full overflow-auto rounded-xl border bg-popover p-1 shadow-xl"
          role="listbox"
        >
          {results.map((result, index) => (
            <li key={`${result.symbol}-${index}`}>
              <button
                type="button"
                onClick={() => choose(result.symbol)}
                onMouseEnter={() => setCursor(index)}
                role="option"
                aria-selected={index === cursor}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                  index === cursor ? "bg-primary/10" : "hover:bg-muted/60",
                )}
              >
                <span className="figure w-28 shrink-0 truncate text-[11px] font-semibold text-primary">{result.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-xs">{result.name}</span>
                <span className="eyebrow shrink-0 text-[9px]">{result.exchange}</span>
              </button>
            </li>
          ))}
          {!results.length && error && (
            <li className="px-3 py-3 text-xs text-muted-foreground">{error}</li>
          )}
        </ul>
      )}
    </div>
  );
}
