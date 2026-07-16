/**
 * useCapabilities — read the backend's runtime capability flags once and cache
 * them process-wide.
 *
 * The only flag today is `brokerageEnabled`, mirroring the backend
 * VIBE_TRADING_ENABLE_BROKERAGE master switch. It defaults to `false` until the
 * fetch resolves so every live-trading surface stays hidden by default — the
 * research-only build never flashes broker UI while `/api` is in flight.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface Capabilities {
  brokerageEnabled: boolean;
}

const DEFAULT_CAPABILITIES: Capabilities = { brokerageEnabled: false };

// Process-wide cache + in-flight promise so many mounted components share one
// `GET /api` round-trip instead of each firing their own.
let cached: Capabilities | null = null;
let inflight: Promise<Capabilities> | null = null;

async function loadCapabilities(): Promise<Capabilities> {
  if (cached) return cached;
  if (!inflight) {
    inflight = api
      .getApiInfo()
      .then((info) => {
        cached = { brokerageEnabled: Boolean(info.capabilities?.brokerage) };
        return cached;
      })
      .catch(() => {
        // Network/parse failure: fail closed to the research-only defaults.
        return DEFAULT_CAPABILITIES;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useCapabilities(): Capabilities {
  const [caps, setCaps] = useState<Capabilities>(cached ?? DEFAULT_CAPABILITIES);

  useEffect(() => {
    let active = true;
    void loadCapabilities().then((next) => {
      if (active) setCaps(next);
    });
    return () => {
      active = false;
    };
  }, []);

  return caps;
}
