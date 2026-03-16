"use client";

import { useState } from "react";
import { Rocket, RefreshCw, TrendingUp, Volume2, Activity, ChevronDown } from "lucide-react";
import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { cn, formatCurrency, formatPercent, pnlColor } from "@/lib/utils";
import type { MomentumSignal } from "@/lib/types";

function MomentumCard({ signal }: { signal: MomentumSignal }) {
  const isStrong = signal.ret_20d > 20;
  const isModerate = signal.ret_20d > 15 && signal.ret_20d <= 20;

  return (
    <div
      className={cn(
        "relative rounded-xl border p-4 transition-colors",
        isStrong
          ? "border-emerald-500/30 bg-emerald-500/5 hover:border-emerald-500/50"
          : isModerate
          ? "border-amber-500/30 bg-amber-500/5 hover:border-amber-500/50"
          : "border-neutral-700 bg-neutral-900/50 hover:border-neutral-600"
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-neutral-100 text-lg">{signal.ticker}</span>
            {isStrong && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                STRONG
              </span>
            )}
            {isModerate && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                MODERATE
              </span>
            )}
          </div>
          <span className="text-sm text-neutral-400">{formatCurrency(signal.price)}</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-xs text-neutral-500">Score</span>
          <span
            className={cn(
              "text-xl font-bold tabular-nums",
              signal.momentum_score >= 80
                ? "text-emerald-400"
                : signal.momentum_score >= 60
                ? "text-blue-400"
                : signal.momentum_score >= 40
                ? "text-amber-400"
                : "text-neutral-400"
            )}
          >
            {signal.momentum_score.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-3 gap-2 text-xs mb-3">
        <div>
          <span className="text-neutral-500 flex items-center gap-1">
            <TrendingUp className="h-3 w-3" />
            20d Ret
          </span>
          <div className={cn("font-medium", pnlColor(signal.ret_20d))}>
            {formatPercent(signal.ret_20d)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">60d Ret</span>
          <div className={cn("font-medium", pnlColor(signal.ret_60d))}>
            {formatPercent(signal.ret_60d)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500 flex items-center gap-1">
            <Volume2 className="h-3 w-3" />
            Vol Ratio
          </span>
          <div
            className={cn(
              "font-medium",
              signal.volume_ratio >= 2
                ? "text-signal-buy"
                : signal.volume_ratio >= 1.5
                ? "text-blue-400"
                : "text-neutral-300"
            )}
          >
            {signal.volume_ratio.toFixed(1)}x
          </div>
        </div>
        <div>
          <span className="text-neutral-500 flex items-center gap-1">
            <Activity className="h-3 w-3" />
            ATR Squeeze
          </span>
          <div
            className={cn(
              "font-medium",
              signal.atr_squeeze < 0.8
                ? "text-signal-buy"
                : signal.atr_squeeze > 1.2
                ? "text-amber-400"
                : "text-neutral-300"
            )}
          >
            {signal.atr_squeeze.toFixed(2)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Trend</span>
          <div
            className={cn(
              "font-medium",
              signal.trend_score >= 80
                ? "text-emerald-400"
                : signal.trend_score >= 50
                ? "text-blue-400"
                : "text-neutral-400"
            )}
          >
            {signal.trend_score.toFixed(0)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">From High</span>
          <div className={cn("font-medium", pnlColor(-signal.pct_from_high))}>
            -{signal.pct_from_high.toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Bottom badges */}
      <div className="flex items-center gap-2 text-xs flex-wrap">
        {signal.analyst_consensus && (
          <span
            className={cn(
              "px-1.5 py-0.5 rounded text-[10px]",
              signal.analyst_consensus.toLowerCase().includes("buy")
                ? "bg-signal-buy/15 text-signal-buy"
                : signal.analyst_consensus.toLowerCase().includes("sell")
                ? "bg-signal-sell/15 text-signal-sell"
                : "bg-neutral-700/50 text-neutral-400"
            )}
          >
            {signal.analyst_consensus}
          </span>
        )}
        {signal.sentiment_label && (
          <span
            className={cn(
              "px-1.5 py-0.5 rounded text-[10px]",
              signal.sentiment_label === "POSITIVE"
                ? "bg-signal-buy/15 text-signal-buy"
                : signal.sentiment_label === "NEGATIVE"
                ? "bg-signal-sell/15 text-signal-sell"
                : "bg-neutral-700/50 text-neutral-400"
            )}
          >
            {signal.sentiment_label}
          </span>
        )}
        <span className="ml-auto text-neutral-500">
          5d: {formatPercent(signal.ret_5d)}
        </span>
      </div>
    </div>
  );
}

export function MomentumTab() {
  const { momentum } = useData();
  const { data, loading, lastUpdated, refresh } = momentum;
  const [refreshing, setRefreshing] = useState(false);
  const [showVetoed, setShowVetoed] = useState(false);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshMomentum();
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const signals = data?.signals ?? [];
  const ranked = signals
    .filter((s) => !s.vetoed)
    .sort((a, b) => b.momentum_score - a.momentum_score);
  const vetoed = signals.filter((s) => s.vetoed);

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Momentum Scanner"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Stats bar */}
        <div className="flex items-center gap-3 text-xs text-neutral-500 flex-wrap">
          <span>
            Scanned:{" "}
            <strong className="text-neutral-300">
              {data?.total_scanned?.toLocaleString() ?? 0}
            </strong>
          </span>
          <span className="text-neutral-700">|</span>
          <span>
            Valid:{" "}
            <strong className="text-signal-buy">{data?.valid ?? ranked.length}</strong>
          </span>
          <span className="text-neutral-700">|</span>
          <span>
            Vetoed: <strong className="text-neutral-400">{vetoed.length}</strong>
          </span>
          {data?.last_scan && (
            <>
              <span className="text-neutral-700">|</span>
              <span>
                Last scan:{" "}
                <strong className="text-neutral-400">{data.last_scan}</strong>
              </span>
            </>
          )}
          {data?.scanning && (
            <span className="text-amber-400 animate-pulse">Scanning...</span>
          )}
          <button
            onClick={handleForceRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 ml-auto px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            Full Scan
          </button>
        </div>

        {/* Momentum signals */}
        {ranked.length > 0 ? (
          <>
            <div className="flex items-center gap-2">
              <Rocket className="h-4 w-4 text-blue-400" />
              <h3 className="text-sm font-semibold text-blue-400">
                Top Momentum ({ranked.length})
              </h3>
              <span className="text-xs text-neutral-500">
                Sorted by momentum score
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {ranked.map((signal) => (
                <MomentumCard key={signal.ticker} signal={signal} />
              ))}
            </div>
          </>
        ) : !loading ? (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4 text-center">
            <p className="text-neutral-400 text-sm font-medium">
              No momentum signals found
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              Run a full scan to discover momentum candidates.
            </p>
          </div>
        ) : null}

        {/* Vetoed section */}
        {vetoed.length > 0 && (
          <>
            <button
              onClick={() => setShowVetoed(!showVetoed)}
              className="flex items-center gap-2 text-xs text-neutral-500 font-medium mt-6 hover:text-neutral-400 transition-colors"
            >
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform",
                  showVetoed && "rotate-180"
                )}
              />
              Vetoed ({vetoed.length})
            </button>
            {showVetoed && (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 opacity-40">
                {vetoed.map((signal) => (
                  <div
                    key={signal.ticker}
                    className="relative rounded-xl border border-neutral-800 bg-neutral-900/30 p-4"
                  >
                    <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-neutral-950/60 z-10">
                      <span className="text-signal-sell font-bold text-sm rotate-[-12deg]">
                        VETOED: {signal.veto_reason}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-semibold text-neutral-100">
                          {signal.ticker}
                        </span>
                        <span className="text-sm text-neutral-400 ml-2">
                          {formatCurrency(signal.price)}
                        </span>
                      </div>
                      <span className="text-neutral-500 text-xs">
                        Score: {signal.momentum_score.toFixed(0)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
