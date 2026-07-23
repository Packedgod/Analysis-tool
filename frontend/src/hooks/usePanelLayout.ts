import { useCallback, useEffect, useMemo, useState } from "react";

/** Width is expressed in 12-column grid units; height in pixels (undefined = auto). */
export type PanelSize = { span?: number; height?: number };

export type PanelLayoutState = {
  order: string[];
  sizes: Record<string, PanelSize>;
};

export const PANEL_COLUMNS = 12;
export const MIN_SPAN = 3;
export const MIN_HEIGHT = 140;

const STORAGE_PREFIX = "vibe.panel-layout.";

function readStored(key: string): PanelLayoutState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PanelLayoutState>;
    if (!parsed || !Array.isArray(parsed.order)) return null;
    return { order: parsed.order.filter((id) => typeof id === "string"), sizes: parsed.sizes ?? {} };
  } catch {
    return null;
  }
}

/**
 * Persisted drag-to-reorder + drag-to-resize state for a set of page sections.
 *
 * Stored layouts are reconciled against the sections that actually exist, so
 * renaming or adding a section never strands a user on a broken saved layout.
 */
export function usePanelLayout(key: string, sectionIds: string[]) {
  const defaults = useMemo(() => sectionIds.join("|"), [sectionIds]);

  const [state, setState] = useState<PanelLayoutState>(() => reconcile(readStored(key), sectionIds));

  // Re-reconcile when the page's section set changes.
  useEffect(() => {
    setState((current) => reconcile(current, sectionIds));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(state));
    } catch {
      /* storage full or unavailable: layout simply is not persisted */
    }
  }, [key, state]);

  const move = useCallback((fromId: string, toId: string) => {
    setState((current) => {
      if (fromId === toId) return current;
      const order = [...current.order];
      const from = order.indexOf(fromId);
      const to = order.indexOf(toId);
      if (from === -1 || to === -1) return current;
      order.splice(to, 0, ...order.splice(from, 1));
      return { ...current, order };
    });
  }, []);

  const resize = useCallback((id: string, patch: PanelSize) => {
    setState((current) => {
      const previous = current.sizes[id] ?? {};
      const next: PanelSize = { ...previous };
      if (patch.span !== undefined) {
        next.span = Math.max(MIN_SPAN, Math.min(PANEL_COLUMNS, Math.round(patch.span)));
      }
      if (patch.height !== undefined) {
        next.height = Math.max(MIN_HEIGHT, Math.round(patch.height));
      }
      return { ...current, sizes: { ...current.sizes, [id]: next } };
    });
  }, []);

  const reset = useCallback(() => {
    setState({ order: sectionIds, sizes: {} });
    try {
      window.localStorage.removeItem(STORAGE_PREFIX + key);
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, defaults]);

  const isCustomised = state.order.join("|") !== sectionIds.join("|") || Object.keys(state.sizes).length > 0;

  return { order: state.order, sizes: state.sizes, move, resize, reset, isCustomised };
}

function reconcile(stored: PanelLayoutState | null, sectionIds: string[]): PanelLayoutState {
  if (!stored) return { order: sectionIds, sizes: {} };
  const known = stored.order.filter((id) => sectionIds.includes(id));
  const added = sectionIds.filter((id) => !known.includes(id));
  const sizes: Record<string, PanelSize> = {};
  for (const id of sectionIds) {
    if (stored.sizes[id]) sizes[id] = stored.sizes[id];
  }
  return { order: [...known, ...added], sizes };
}
