"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Database, Wifi, Clock, AlertTriangle, CheckCircle } from "lucide-react";

interface DataStatus {
  timestamp: string;
  today: string;
  market_session: string;
  cache: {
    stale_count: number;
    total_checked: number;
    tickers: Record<string, { latest: string | null; rows: number; fresh: boolean }>;
  };
  quotes: {
    cached_count: number;
    tickers: Record<string, { price: number; age_sec: number | null }>;
  };
  extended_hours: {
    available: number;
    session: string;
    tickers: Record<string, { ext_price: number | null; session: string }>;
  };
  market_regime: {
    regime: string;
    pause_entries: boolean;
    spy_5d_return?: number;
    spy_price?: number;
    spy_price_live?: number;
    vix?: number;
  };
  scan_cache_age_min: number | null;
  system: { stage: string; message: string; progress: number };
}

const SESSION_LABELS: Record<string, { label: string; color: string }> = {
  PRE_MARKET: { label: "Pre-Market", color: "text-blue-400" },
  REGULAR: { label: "Market Open", color: "text-emerald-400" },
  AFTER_HOURS: { label: "After Hours", color: "text-amber-400" },
  CLOSED: { label: "Market Closed", color: "text-neutral-500" },
};

const REGIME_COLORS: Record<string, string> = {
  HEALTHY: "text-emerald-400",
  CAUTION: "text-amber-400",
  FEAR: "text-orange-400",
  DECLINING: "text-red-400",
  CRISIS: "text-red-500",
  BEAR: "text-red-600",
};

export function DataStatusBar() {
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v2/data/status`,
          { cache: "no-store" }
        );
        if (res.ok) {
          setStatus(await res.json());
          setError(false);
        } else {
          setError(true);
        }
      } catch {
        setError(true);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 px-4 py-1.5 bg-red-950/50 border-b border-red-800/40 text-[11px] text-red-400">
        <AlertTriangle className="h-3 w-3" />
        <span>Backend offline</span>
      </div>
    );
  }

  if (!status) return null;

  const session = SESSION_LABELS[status.market_session] ?? SESSION_LABELS.CLOSED;
  const regime = status.market_regime;
  const regimeColor = REGIME_COLORS[regime?.regime ?? ""] ?? "text-neutral-400";
  const cacheOk = status.cache.stale_count === 0;
  const quotesActive = status.quotes.cached_count > 0;
  const extCount = status.extended_hours.available;
  const scanAge = status.scan_cache_age_min;
  const sys = status.system;

  return (
    <div className="flex items-center gap-4 px-4 py-1 bg-neutral-900/80 border-b border-neutral-800/60 text-[11px] text-neutral-500 overflow-x-auto whitespace-nowrap">
      {/* Market Session */}
      <div className="flex items-center gap-1.5">
        <div className={`h-1.5 w-1.5 rounded-full ${
          status.market_session === "REGULAR" ? "bg-emerald-400 animate-pulse" :
          status.market_session === "CLOSED" ? "bg-neutral-600" : "bg-amber-400 animate-pulse"
        }`} />
        <span className={session.color}>{session.label}</span>
      </div>

      <span className="text-neutral-700">|</span>

      {/* Market Regime */}
      <div className="flex items-center gap-1.5">
        <span className={regimeColor}>
          {regime?.regime ?? "?"}
          {regime?.pause_entries && " (PAUSED)"}
        </span>
        {regime?.spy_5d_return != null && (
          <span className="text-neutral-600">
            SPY 5d: {regime.spy_5d_return >= 0 ? "+" : ""}{regime.spy_5d_return.toFixed(1)}%
          </span>
        )}
        {regime?.vix != null && (
          <span className="text-neutral-600">VIX: {regime.vix.toFixed(1)}</span>
        )}
      </div>

      <span className="text-neutral-700">|</span>

      {/* Data Cache */}
      <div className="flex items-center gap-1.5">
        <Database className="h-3 w-3" />
        {cacheOk ? (
          <span className="text-emerald-500">
            <CheckCircle className="h-3 w-3 inline mr-0.5" />
            Cache fresh
          </span>
        ) : (
          <span className="text-red-400">
            <AlertTriangle className="h-3 w-3 inline mr-0.5" />
            {status.cache.stale_count} stale
          </span>
        )}
      </div>

      <span className="text-neutral-700">|</span>

      {/* Live Quotes */}
      <div className="flex items-center gap-1.5">
        <Wifi className="h-3 w-3" />
        <span className={quotesActive ? "text-emerald-500" : "text-red-400"}>
          {status.quotes.cached_count} quotes
        </span>
        {extCount > 0 && (
          <span className="text-amber-400">+{extCount} ext</span>
        )}
      </div>

      {/* Scan Age */}
      {scanAge != null && (
        <>
          <span className="text-neutral-700">|</span>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span className={scanAge > 120 ? "text-red-400" : scanAge > 60 ? "text-amber-400" : "text-neutral-500"}>
              Scan: {scanAge < 1 ? "<1" : Math.round(scanAge)}m ago
            </span>
          </div>
        </>
      )}

      {/* System Status */}
      {sys?.stage && sys.stage !== "idle" && sys.stage !== "ready" && (
        <>
          <span className="text-neutral-700">|</span>
          <span className="text-blue-400 animate-pulse">{sys.message || sys.stage}</span>
        </>
      )}
    </div>
  );
}
