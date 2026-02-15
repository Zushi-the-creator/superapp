"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { ScoreGauge } from "@/components/shared/ScoreGauge";
import { RegimeBadge, SignalBadge, TierBadge } from "@/components/shared/Badges";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { api } from "@/lib/api";
import { RefreshCw, ArrowUp, Zap } from "lucide-react";
import { useState } from "react";
import type { ScanOpportunity, HoldingScore } from "@/lib/types";

export function OpportunitiesTab() {
  const { scanner } = useData();
  const { data, loading, lastUpdated, refresh } = scanner;
  const [refreshing, setRefreshing] = useState(false);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshScan();
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const opportunities = data?.opportunities ?? [];
  const holdingsScores = data?.holdings_scores ?? [];
  const worstHolding = data?.worst_holding ?? "";
  const worstScore = data?.worst_score ?? 0;

  // Filter out current holdings from opportunities
  const holdingTickers = new Set(holdingsScores.map((h) => h.ticker));
  const nonHeld = opportunities.filter((o) => !holdingTickers.has(o.ticker));

  // Upgrades = stocks that beat current holdings
  const upgrades = nonHeld.filter((o) => o.is_upgrade && !o.vetoed);

  // Group non-vetoed, non-held, non-upgrade by V2.2 tier (avoid duplicates with upgrades)
  const nonVetoed = nonHeld.filter((o) => !o.vetoed && !o.is_upgrade);
  const extreme = nonVetoed.filter((o) => o.tier === "EXTREME");
  const strong = nonVetoed.filter((o) => o.tier === "STRONG");
  const standard = nonVetoed.filter((o) => o.tier === "STANDARD" || o.tier === "NONE");
  const vetoed = nonHeld.filter((o) => o.vetoed);

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Scanner Opportunities"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Stats bar */}
        <div className="flex items-center gap-4 text-xs text-neutral-500">
          <span>Scanned: {data?.total_scanned?.toLocaleString() ?? 0}</span>
          <span>Passed: {data?.passed ?? 0}</span>
          {extreme.length > 0 && <span className="text-purple-400">Extreme: {extreme.length}</span>}
          {strong.length > 0 && <span className="text-blue-400">Strong: {strong.length}</span>}
          <span>Upgrades: {upgrades.length}</span>
          <button
            onClick={handleForceRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 ml-auto px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            Full Scan ({data?.total_scanned?.toLocaleString() ?? "2,984"} stocks)
          </button>
        </div>

        {/* Current holdings scores for reference */}
        {holdingsScores.length > 0 && (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <h3 className="text-xs text-neutral-500 font-medium mb-2">
              Current Portfolio Scores (stocks below must beat these)
            </h3>
            <div className="flex flex-wrap gap-3">
              {holdingsScores.map((h: HoldingScore) => (
                <div
                  key={h.ticker}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs",
                    h.ticker === worstHolding
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
                      : "border-neutral-700 bg-neutral-800/50 text-neutral-300"
                  )}
                >
                  <span className="font-medium">{h.ticker}</span>
                  <span>Score: {h.score.toFixed(2)}</span>
                  <span className="text-neutral-500">
                    (WR {h.win_rate.toFixed(0)}% / ZR {formatPercent(h.zone_return)})
                  </span>
                  {h.ticker === worstHolding && (
                    <span className="text-amber-400 font-medium">WEAKEST</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* UPGRADE section - stocks that beat current holdings */}
        {upgrades.length > 0 && (
          <>
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-signal-buy" />
              <h3 className="text-sm font-semibold text-signal-buy">
                Portfolio Upgrades ({upgrades.length})
              </h3>
              <span className="text-xs text-neutral-500">
                These stocks score higher than current holdings
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {upgrades.map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}

        {upgrades.length === 0 && !loading && (
          <div className="rounded-xl border border-signal-buy/20 bg-signal-buy/5 p-4 text-center">
            <p className="text-signal-buy text-sm font-medium">
              Portfolio is optimal - no stock beats current holdings
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              Scanned {data?.total_scanned?.toLocaleString() ?? 0} stocks
            </p>
          </div>
        )}

        {/* V2.2 Tier: EXTREME */}
        {extreme.length > 0 && (
          <>
            <div className="flex items-center gap-2 mt-4">
              <div className="h-2 w-2 rounded-full bg-purple-500 ring-2 ring-purple-500/30" />
              <h3 className="text-sm font-semibold text-purple-300">
                V2.2 EXTREME ({extreme.length})
              </h3>
              <span className="text-xs text-neutral-500">
                RSI(2) &lt; 5 + above SMA200 — highest conviction
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {extreme.map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}

        {/* V2.2 Tier: STRONG */}
        {strong.length > 0 && (
          <>
            <div className="flex items-center gap-2 mt-4">
              <div className="h-2 w-2 rounded-full bg-blue-500 ring-2 ring-blue-500/30" />
              <h3 className="text-sm font-semibold text-blue-300">
                V2.2 STRONG ({strong.length})
              </h3>
              <span className="text-xs text-neutral-500">
                RSI(2) &lt; 20 + dual-TF or volume spike
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {strong.map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}

        {/* V2.2 Tier: STANDARD */}
        {standard.length > 0 && (
          <>
            <div className="flex items-center gap-2 mt-4">
              <div className="h-2 w-2 rounded-full bg-neutral-500 ring-2 ring-neutral-500/30" />
              <h3 className="text-sm font-semibold text-neutral-400">
                V2.2 STANDARD ({standard.length})
              </h3>
              <span className="text-xs text-neutral-500">
                RSI(2) &lt; 20 + above SMA50
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {standard.slice(0, 12).map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}

        {/* Vetoed section */}
        {vetoed.length > 0 && (
          <>
            <h3 className="text-xs text-neutral-500 font-medium mt-6">
              Vetoed ({vetoed.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 opacity-50">
              {vetoed.slice(0, 6).map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function OpportunityCard({
  opp,
  holdingsScores,
}: {
  opp: ScanOpportunity;
  holdingsScores: HoldingScore[];
}) {
  return (
    <div
      className={cn(
        "relative rounded-xl border p-4 transition-colors",
        opp.vetoed
          ? "border-neutral-800 bg-neutral-900/30"
          : opp.is_upgrade
          ? "border-signal-buy/40 bg-signal-buy/5 hover:border-signal-buy/60"
          : opp.tier === "EXTREME"
          ? "border-purple-500/30 bg-purple-500/5 hover:border-purple-500/50"
          : opp.tier === "STRONG"
          ? "border-blue-500/30 bg-blue-500/5 hover:border-blue-500/50"
          : "border-neutral-800 bg-neutral-900/50 hover:border-neutral-700"
      )}
    >
      {opp.vetoed && (
        <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-neutral-950/60 z-10">
          <span className="text-signal-sell font-bold text-sm rotate-[-12deg]">
            VETOED: {opp.veto_reason}
          </span>
        </div>
      )}

      {/* Upgrade badge */}
      {opp.is_upgrade && (
        <div className="flex items-center gap-1.5 mb-2 px-2 py-1 rounded bg-signal-buy/15 w-fit">
          <ArrowUp className="h-3 w-3 text-signal-buy" />
          <span className="text-xs font-medium text-signal-buy">
            BEATS {opp.beats_holdings.join(", ")}
          </span>
        </div>
      )}

      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-neutral-100">{opp.ticker}</span>
            <TierBadge tier={opp.tier} />
            <RegimeBadge regime={opp.regime} />
          </div>
          <span className="text-sm text-neutral-400">
            {formatCurrency(opp.price)}
          </span>
        </div>
        <ScoreGauge value={opp.win_rate} size={54} />
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs mb-3">
        <div>
          <span className="text-neutral-500">Zone Return</span>
          <div className={cn("font-medium", pnlColor(opp.zone_return))}>
            {formatPercent(opp.zone_return)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Win Rate</span>
          <div className="text-neutral-200 font-medium">
            {opp.win_rate.toFixed(1)}%
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Hold</span>
          <div className="text-neutral-200">{opp.hold_days}d</div>
        </div>
        <div>
          <span className="text-neutral-500">Score</span>
          <div className={cn("font-medium", opp.is_upgrade ? "text-signal-buy" : "text-neutral-200")}>
            {opp.score.toFixed(2)}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs">
        {opp.analyst_consensus && (
          <SignalBadge signal={opp.analyst_consensus} />
        )}
        {opp.sentiment_label && (
          <span
            className={cn(
              "px-1.5 py-0.5 rounded text-[10px]",
              opp.sentiment_label === "POSITIVE"
                ? "bg-signal-buy/15 text-signal-buy"
                : opp.sentiment_label === "NEGATIVE"
                ? "bg-signal-sell/15 text-signal-sell"
                : "bg-neutral-700/50 text-neutral-400"
            )}
          >
            {opp.sentiment_label}
          </span>
        )}
        <span className="ml-auto text-neutral-500">
          {opp.trades} trades
        </span>
      </div>
    </div>
  );
}
