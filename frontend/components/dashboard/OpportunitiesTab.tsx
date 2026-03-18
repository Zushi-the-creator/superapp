"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { ScoreGauge } from "@/components/shared/ScoreGauge";
import { RegimeBadge, SignalBadge, TierBadge } from "@/components/shared/Badges";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { api } from "@/lib/api";
import { RefreshCw, ArrowUp, Zap, ShieldCheck, DollarSign, Star, ChevronDown } from "lucide-react";
import { useState, useEffect } from "react";
import type { ScanOpportunity, HoldingScore } from "@/lib/types";

const TIER_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  BEST: { border: "border-emerald-500/40", bg: "bg-emerald-500/5", text: "text-emerald-400" },
  GOOD: { border: "border-blue-500/30", bg: "bg-blue-500/5", text: "text-blue-400" },
  FAIR: { border: "border-neutral-700", bg: "bg-neutral-900/50", text: "text-neutral-300" },
  WEAK: { border: "border-neutral-800", bg: "bg-neutral-900/30", text: "text-neutral-500" },
  POOR: { border: "border-neutral-800", bg: "bg-neutral-950/50", text: "text-neutral-600" },
};

export function OpportunitiesTab() {
  const { scanner } = useData();
  const { data, loading, lastUpdated, refresh } = scanner;
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [combined, setCombined] = useState<import("@/lib/types").CombinedSignal[]>([]);
  const [combinedStats, setCombinedStats] = useState({ mr: 0, mom: 0, both: 0 });

  // Fetch combined on mount and refresh
  const fetchCombined = async () => {
    try {
      const res = await api.getCombined();
      setCombined(res.signals ?? []);
      setCombinedStats({ mr: res.mean_reversion ?? 0, mom: res.momentum ?? 0, both: res.both ?? 0 });
    } catch {}
  };

  // Fetch combined on mount
  useEffect(() => { fetchCombined(); }, []);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshAll();
      await refresh();
      // Refetch combined after a delay to allow scans to complete
      setTimeout(fetchCombined, 5000);
    } finally {
      setRefreshing(false);
    }
  };

  const opportunities = data?.opportunities ?? [];
  const holdingsScores = data?.holdings_scores ?? [];
  const worstHolding = data?.worst_holding ?? "";

  // Filter out current holdings
  const holdingTickers = new Set(holdingsScores.map((h) => h.ticker));
  const allStocks = opportunities.filter((o) => !holdingTickers.has(o.ticker));

  // Separate vetoed and ranked
  const vetoed = allStocks.filter((o) => o.vetoed);
  const ranked = allStocks.filter((o) => !o.vetoed);

  // Sort ranked by composite_score descending
  const sorted = [...ranked].sort((a, b) => b.composite_score - a.composite_score);

  // Best candidates = meets_strict
  const bestCandidates = sorted.filter((o) => o.meets_strict);

  // Tier counts
  const tierCounts = {
    BEST: sorted.filter((o) => o.quality_tier === "BEST").length,
    GOOD: sorted.filter((o) => o.quality_tier === "GOOD").length,
    FAIR: sorted.filter((o) => o.quality_tier === "FAIR").length,
    WEAK: sorted.filter((o) => o.quality_tier === "WEAK").length,
    POOR: sorted.filter((o) => o.quality_tier === "POOR").length,
  };

  // Show top 30 by default, all when expanded
  const displayLimit = showAll ? sorted.length : 30;
  const displayStocks = sorted.slice(0, displayLimit);

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Stock Scanner"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Stats bar */}
        <div className="flex items-center gap-3 text-xs text-neutral-500 flex-wrap">
          <span>Scanned: <strong className="text-neutral-300">{data?.total_scanned?.toLocaleString() ?? 0}</strong></span>
          <span className="text-neutral-700">|</span>
          <span>Ranked: <strong className="text-neutral-300">{data?.ranked_count ?? ranked.length}</strong></span>
          <span className="text-neutral-700">|</span>
          <span>Strict: <strong className="text-signal-buy">{data?.passed ?? bestCandidates.length}</strong></span>
          <span className="text-neutral-700">|</span>
          {Object.entries(tierCounts).map(([tier, count]) => count > 0 && (
            <span key={tier} className={TIER_COLORS[tier]?.text}>
              {tier}: {count}
            </span>
          ))}
          <button
            onClick={handleForceRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 ml-auto px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            Full Scan
          </button>
        </div>

        {/* Current holdings scores */}
        {holdingsScores.length > 0 && (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <h3 className="text-xs text-neutral-500 font-medium mb-2">
              Current Holdings
            </h3>
            <div className="flex flex-wrap gap-3">
              {holdingsScores.map((h: HoldingScore) => (
                <div
                  key={h.ticker}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs",
                    h.exit_triggered
                      ? "border-signal-sell/40 bg-signal-sell/10 text-signal-sell"
                      : h.ticker === worstHolding
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
                      : "border-neutral-700 bg-neutral-800/50 text-neutral-300"
                  )}
                >
                  <span className="font-medium">{h.ticker}</span>
                  <span>Score: {h.score.toFixed(2)}</span>
                  <span className="text-neutral-500">
                    (WR {h.win_rate.toFixed(0)}% / ZR {formatPercent(h.zone_return)})
                  </span>
                  {h.exit_triggered && (
                    <span className="text-signal-sell font-bold animate-pulse">EXIT</span>
                  )}
                  {!h.exit_triggered && h.ticker === worstHolding && (
                    <span className="text-amber-400 font-medium">WEAKEST</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Combined Signals — MR + Momentum unified ranking */}
        {combined.length > 0 && (
          <>
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-400" />
              <h3 className="text-sm font-semibold text-amber-400">
                Top Entries — Combined ({combined.length})
              </h3>
              <span className="text-xs text-neutral-500">
                {combinedStats.mr} dip buys · {combinedStats.mom} breakouts · {combinedStats.both} both
                {combined[0]?.data_date && <> · Evaluated: {combined[0].data_date}</>}
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {combined.slice(0, 12).map((sig) => (
                <div key={sig.ticker} className={cn(
                  "rounded-lg border p-3 space-y-2",
                  sig.strategy === "BOTH" ? "border-amber-500/40 bg-amber-500/5" :
                  sig.strategy === "MOMENTUM" ? "border-blue-500/30 bg-blue-500/5" :
                  "border-emerald-500/30 bg-emerald-500/5"
                )}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-neutral-100">{sig.ticker}</span>
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium",
                        sig.strategy === "BOTH" ? "bg-amber-500/20 text-amber-400" :
                        sig.strategy === "MOMENTUM" ? "bg-blue-500/20 text-blue-400" :
                        "bg-emerald-500/20 text-emerald-400"
                      )}>{sig.strategy_label}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-neutral-300 font-medium">{formatCurrency(sig.price)}</span>
                      <span className={cn("text-[9px] ml-1", sig.price_is_live ? "text-signal-buy" : "text-signal-sell")}>
                        {sig.price_is_live ? "LIVE" : "DELAYED"}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <span className="text-neutral-500">Score</span>
                      <div className={cn("font-bold",
                        sig.score >= 60 ? "text-emerald-400" :
                        sig.score >= 40 ? "text-blue-400" : "text-neutral-300"
                      )}>{sig.score.toFixed(0)}</div>
                    </div>
                    {sig.strategy !== "MOMENTUM" && (
                      <div>
                        <span className="text-neutral-500">WR</span>
                        <div className="text-neutral-200">{sig.confidence.toFixed(0)}% <span className="text-neutral-600">({sig.trades}t)</span></div>
                      </div>
                    )}
                    {sig.strategy !== "MEAN_REVERSION" && (
                      <div>
                        <span className="text-neutral-500">20d Ret</span>
                        <div className={cn(pnlColor(sig.ret_20d))}>{sig.ret_20d > 0 ? "+" : ""}{sig.ret_20d.toFixed(1)}%</div>
                      </div>
                    )}
                    <div>
                      <span className="text-neutral-500">Vol</span>
                      <div className={cn(sig.volume_ratio >= 2 ? "text-signal-buy" : "text-neutral-300")}>{sig.volume_ratio.toFixed(1)}x</div>
                    </div>
                    {sig.expected_return > 0 && (
                      <div>
                        <span className="text-neutral-500">Avg Ret</span>
                        <div className={cn(pnlColor(sig.expected_return))}>{sig.expected_return > 0 ? "+" : ""}{sig.expected_return.toFixed(1)}%</div>
                      </div>
                    )}
                    {sig.atr_squeeze > 0 && sig.atr_squeeze < 1 && (
                      <div>
                        <span className="text-neutral-500">Squeeze</span>
                        <div className={cn(sig.atr_squeeze < 0.7 ? "text-signal-buy" : "text-neutral-300")}>{sig.atr_squeeze.toFixed(2)}</div>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-[10px]">
                    {sig.analyst_consensus && <span className="px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400">{sig.analyst_consensus}</span>}
                    {sig.sentiment_label && <span className={cn("px-1.5 py-0.5 rounded",
                      sig.sentiment_label === "POSITIVE" ? "bg-emerald-500/10 text-emerald-400" :
                      sig.sentiment_label === "NEGATIVE" ? "bg-red-500/10 text-red-400" :
                      "bg-neutral-800 text-neutral-400"
                    )}>{sig.sentiment_label}</span>}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Best Candidates (meets strict) */}
        {bestCandidates.length > 0 && (
          <>
            <div className="flex items-center gap-2">
              <Star className="h-4 w-4 text-emerald-400" />
              <h3 className="text-sm font-semibold text-emerald-400">
                Best Candidates ({bestCandidates.length})
              </h3>
              <span className="text-xs text-neutral-500">
                Passes ALL strict filters (RSI&lt;10, ATR&gt;3%, WR&gt;65%, buf&gt;5%)
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {bestCandidates.slice(0, 6).map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
          </>
        )}

        {/* All Ranked Stocks */}
        <div className="flex items-center gap-2 mt-2">
          <Zap className="h-4 w-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-blue-400">
            All Ranked Stocks ({sorted.length})
          </h3>
          <span className="text-xs text-neutral-500">
            Sorted by composite score (0-100)
          </span>
        </div>

        {displayStocks.length > 0 ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {displayStocks.map((opp) => (
                <OpportunityCard
                  key={opp.ticker}
                  opp={opp}
                  holdingsScores={holdingsScores}
                />
              ))}
            </div>
            {sorted.length > 30 && !showAll && (
              <button
                onClick={() => setShowAll(true)}
                className="flex items-center gap-1.5 mx-auto px-4 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm transition-colors"
              >
                <ChevronDown className="h-4 w-4" />
                Show all {sorted.length} stocks
              </button>
            )}
          </>
        ) : !loading ? (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4 text-center">
            <p className="text-neutral-400 text-sm font-medium">
              No ranked stocks found
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              Run a full scan to discover candidates.
            </p>
          </div>
        ) : null}

        {/* Vetoed section */}
        {vetoed.length > 0 && (
          <>
            <h3 className="text-xs text-neutral-500 font-medium mt-6">
              Vetoed ({vetoed.length}) — penny stocks, earnings risk, or strongly negative sentiment
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 opacity-40">
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

function CompositeBar({ score, tier }: { score: number; tier: string }) {
  const color =
    tier === "BEST" ? "bg-emerald-500" :
    tier === "GOOD" ? "bg-blue-500" :
    tier === "FAIR" ? "bg-amber-500" :
    tier === "WEAK" ? "bg-orange-500" :
    "bg-red-500";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-neutral-800 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
      <span className={cn("text-[10px] font-bold tabular-nums min-w-[2rem] text-right",
        TIER_COLORS[tier]?.text ?? "text-neutral-500"
      )}>
        {score.toFixed(0)}
      </span>
    </div>
  );
}

function QualityBadge({ tier }: { tier: string }) {
  const styles = TIER_COLORS[tier] ?? TIER_COLORS.POOR;
  return (
    <span className={cn(
      "px-1.5 py-0.5 rounded text-[10px] font-bold border",
      styles.border, styles.bg, styles.text
    )}>
      {tier}
    </span>
  );
}

function OpportunityCard({
  opp,
  holdingsScores,
}: {
  opp: ScanOpportunity;
  holdingsScores: HoldingScore[];
}) {
  const tierStyle = TIER_COLORS[opp.quality_tier] ?? TIER_COLORS.FAIR;

  return (
    <div
      className={cn(
        "relative rounded-xl border p-4 transition-colors",
        opp.vetoed
          ? "border-neutral-800 bg-neutral-900/30"
          : opp.meets_strict
          ? "border-emerald-500/30 bg-emerald-500/5 hover:border-emerald-500/50"
          : cn(tierStyle.border, tierStyle.bg, "hover:brightness-110")
      )}
    >
      {opp.vetoed && (
        <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-neutral-950/60 z-10">
          <span className="text-signal-sell font-bold text-sm rotate-[-12deg]">
            VETOED: {opp.veto_reason}
          </span>
        </div>
      )}

      {/* Action badge */}
      {opp.is_upgrade ? (
        <div className="flex items-center gap-1.5 mb-2 px-2 py-1 rounded bg-signal-buy/15 w-fit">
          <ArrowUp className="h-3 w-3 text-signal-buy" />
          <span className="text-xs font-medium text-signal-sell">
            SELL {opp.beats_holdings.join(", ")}
          </span>
          <span className="text-xs text-neutral-500">→</span>
          <span className="text-xs font-medium text-signal-buy">
            BUY {opp.ticker}
          </span>
        </div>
      ) : opp.meets_strict && !opp.vetoed ? (
        <div className="flex items-center gap-1.5 mb-2 px-2 py-1 rounded bg-emerald-500/15 w-fit">
          <Star className="h-3 w-3 text-emerald-400" />
          <span className="text-xs font-medium text-emerald-300">
            STRICT PASS
          </span>
        </div>
      ) : null}

      {/* Header row */}
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-neutral-100">{opp.ticker}</span>
            <QualityBadge tier={opp.quality_tier || "POOR"} />
            <TierBadge tier={opp.tier} />
            <RegimeBadge regime={opp.regime} />
          </div>
          <span className="text-sm text-neutral-400">
            {formatCurrency(opp.price)}
          </span>
        </div>
        <ScoreGauge value={opp.composite_score} size={54} />
      </div>

      {/* Composite score bar */}
      <div className="mb-3">
        <CompositeBar score={opp.composite_score} tier={opp.quality_tier || "POOR"} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs mb-3">
        <div>
          <span className="text-neutral-500">Zone Return</span>
          <div className={cn("font-medium", pnlColor(opp.zone_return))}>
            {formatPercent(opp.zone_return)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Win Rate</span>
          <div className="text-neutral-200 font-medium">
            {(opp.bayesian_wr ?? opp.win_rate).toFixed(1)}%
            {opp.bayesian_wr != null && Math.abs(opp.bayesian_wr - opp.win_rate) >= 2 && (
              <span className="text-[10px] text-neutral-500 ml-1">(raw: {opp.win_rate.toFixed(0)}%)</span>
            )}
          </div>
          <div className={cn(
            "text-[10px] font-medium",
            (opp.trades ?? 0) < 10 ? "text-signal-sell" :
            (opp.trades ?? 0) < 20 ? "text-amber-400" :
            "text-neutral-500"
          )}>
            {opp.trades} trades
          </div>
        </div>
        <div>
          <span className="text-neutral-500">RSI(2)</span>
          <div className={cn("font-medium", opp.rsi2 < 10 ? "text-signal-buy" : "text-neutral-300")}>
            {opp.rsi2.toFixed(0)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">ATR%</span>
          <div className={cn("font-medium", opp.atr_pct >= 3 ? "text-signal-buy" : "text-neutral-400")}>
            {(opp.atr_pct ?? 0).toFixed(1)}%
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Buffer</span>
          <div className={cn("font-medium", (opp.sma50_buffer ?? 0) >= 5 ? "text-signal-buy" : "text-neutral-400")}>
            {(opp.sma50_buffer ?? 0).toFixed(0)}%
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Score</span>
          <div className={cn("font-medium", tierStyle.text)}>
            {opp.score.toFixed(2)}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs flex-wrap">
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
        {opp.wr_tier && (
          <span
            className={cn(
              "px-1.5 py-0.5 rounded text-[10px] font-bold",
              opp.wr_tier === "TIER1"
                ? "bg-emerald-500/20 text-emerald-400"
                : opp.wr_tier === "TIER2"
                ? "bg-blue-500/20 text-blue-400"
                : "bg-amber-500/20 text-amber-400"
            )}
          >
            {opp.wr_tier}
          </span>
        )}
        <span className="ml-auto text-neutral-500">
          {opp.trades} trades
        </span>
      </div>
    </div>
  );
}
