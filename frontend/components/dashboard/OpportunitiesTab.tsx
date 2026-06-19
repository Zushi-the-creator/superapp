"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { ScoreGauge } from "@/components/shared/ScoreGauge";
import { RegimeBadge, SignalBadge, TierBadge } from "@/components/shared/Badges";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { api } from "@/lib/api";
import { RefreshCw, ArrowUp, Zap, ShieldCheck, DollarSign, Star, ChevronDown, Loader2 } from "lucide-react";
import { useState, useEffect } from "react";
import type { ScanOpportunity, HoldingScore } from "@/lib/types";

const TIER_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  BEST: { border: "border-emerald-500/40", bg: "bg-emerald-500/5", text: "text-emerald-400" },
  GOOD: { border: "border-blue-500/30", bg: "bg-blue-500/5", text: "text-blue-400" },
  FAIR: { border: "border-neutral-700", bg: "bg-neutral-900/50", text: "text-neutral-300" },
  WEAK: { border: "border-neutral-800", bg: "bg-neutral-900/30", text: "text-neutral-500" },
  POOR: { border: "border-neutral-800", bg: "bg-neutral-950/50", text: "text-neutral-600" },
};

type CombinedResponseExt = import("@/lib/types").CombinedResponse & {
  tier_counts?: Record<string, number>;
  ranked_count?: number;
  total_scanned?: number;
  passed?: number;
  upgrades?: number;
  holdings_scores?: { ticker: string; score: number; zone_return: number; win_rate: number; exit_triggered: boolean; signal: string }[];
  worst_holding?: string;
  worst_score?: number;
  refreshing?: boolean;
  scanning?: boolean;
  cache_stale?: boolean;
  cache_age_min?: number;
};

export function OpportunitiesTab() {
  // V3.3 SSOT — /scan/combined is the SOLE entries-tab data source. No more
  // useData().scanner (/scan/opportunities) here. /scan/opportunities still
  // serves the holdings-rotation backend logic but the frontend doesn't touch it.
  const [data, setData] = useState<CombinedResponseExt | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [systemStatus, setSystemStatus] = useState({ stage: "idle", message: "", progress: 0 });
  const [combinedError, setCombinedError] = useState<string | null>(null);

  const fetchCombined = async () => {
    try {
      const res = (await api.getCombined()) as CombinedResponseExt;
      setData(res);
      if (res.system_status) setSystemStatus(res.system_status as { stage: string; message: string; progress: number });
      setLastUpdated(new Date());
      setLoading(false);
      setCombinedError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("[OpportunitiesTab] /scan/combined fetch failed:", e);
      setCombinedError(msg);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCombined();
    const interval = setInterval(fetchCombined, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    try {
      api.refreshAll().catch(() => {});
      await fetchCombined();
      const poll = setInterval(async () => { await fetchCombined(); }, 5000);
      setTimeout(() => { clearInterval(poll); setRefreshing(false); }, 30000);
    } catch {
      setRefreshing(false);
    }
  };

  // Derive everything from the single SSOT response.
  const combined = data?.signals ?? [];
  const holdingsScores = data?.holdings_scores ?? [];
  const worstHolding = data?.worst_holding ?? "";
  const tierCounts = data?.tier_counts ?? { BEST: 0, GOOD: 0, FAIR: 0, WEAK: 0, POOR: 0 };
  const dataDate = data?.data_date ?? "";
  const cacheAge = data?.cache_age_min ?? 0;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Stock Scanner"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={fetchCombined}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Stats bar */}
        <div className="flex items-center gap-3 text-xs text-neutral-500 flex-wrap">
          {dataDate && (
            <span className={cn(cacheAge > 60 ? "text-signal-sell" : "text-neutral-500")}>
              Scan: <strong className={cacheAge > 60 ? "text-signal-sell" : "text-neutral-300"}>
                {cacheAge < 1 ? "just now" : cacheAge < 60 ? `${Math.round(cacheAge)}m ago` : cacheAge < 1440 ? `${Math.round(cacheAge / 60)}h ago` : `${Math.round(cacheAge / 1440)}d ago`}
              </strong>
              <span className="ml-1 text-neutral-600">(data: {dataDate})</span>
            </span>
          )}
          <span className="text-neutral-700">|</span>
          <span>Scanned: <strong className="text-neutral-300">{data?.total_scanned?.toLocaleString() ?? 0}</strong></span>
          <span className="text-neutral-700">|</span>
          <span>Ranked: <strong className="text-neutral-300">{data?.ranked_count ?? combined.length}</strong></span>
          <span className="text-neutral-700">|</span>
          <span>Strict: <strong className="text-signal-buy">{data?.passed ?? 0}</strong></span>
          <span className="text-neutral-700">|</span>
          {Object.entries(tierCounts).map(([tier, count]) => count > 0 && (
            <span key={tier} className={TIER_COLORS[tier]?.text}>
              {tier}: {count}
            </span>
          ))}
          {(data?.refreshing || data?.scanning) && (
            <span className="inline-flex items-center gap-1.5 text-amber-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Refreshing 3K stocks…</span>
            </span>
          )}
          {data?.cache_stale && !data?.refreshing && !data?.scanning && (
            <span className="text-signal-sell">Stale — refresh queued</span>
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

        {/* Market regime info — V2.6: DECLINING/CRISIS pauses entries */}
        {data?.market_regime && data.market_regime.regime !== "HEALTHY" && data.market_regime.regime !== "UNKNOWN" && (
          <div className={cn(
            "rounded-lg border px-4 py-2 flex items-center gap-3",
            data.market_regime.pause_entries
              ? "border-signal-sell/40 bg-signal-sell/10"
              : "border-amber-500/30 bg-amber-500/5"
          )}>
            <ShieldCheck className={cn("h-4 w-4 flex-shrink-0", data.market_regime.pause_entries ? "text-signal-sell" : "text-amber-400")} />
            <div className={cn("text-xs", data.market_regime.pause_entries ? "text-signal-sell font-medium" : "text-neutral-400")}>
              {data.market_regime.pause_entries
                ? `ENTRIES PAUSED — ${data.market_regime.reason}`
                : `Market: ${data.market_regime.regime} — SPY 5d: ${(data.market_regime.spy_5d_return ?? 0).toFixed(1)}%${data.market_regime.vix > 0 ? `, VIX: ${data.market_regime.vix.toFixed(0)}` : ""} — reduce position size to ${data.market_regime.position_size_pct}%`
              }
            </div>
          </div>
        )}

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

        {/* System status banner */}
        {systemStatus.stage !== "idle" && systemStatus.stage !== "ready" && (
          <div className={cn(
            "rounded-lg border px-4 py-3 flex items-center gap-3",
            systemStatus.stage === "error" ? "border-red-500/30 bg-red-500/5" : "border-blue-500/30 bg-blue-500/5"
          )}>
            {systemStatus.stage !== "error" && (
              <RefreshCw className="h-4 w-4 text-blue-400 animate-spin" />
            )}
            <div>
              <div className="text-sm font-medium text-neutral-200">{systemStatus.message}</div>
              {systemStatus.progress > 0 && systemStatus.progress < 100 && (
                <div className="w-48 h-1.5 bg-neutral-800 rounded-full mt-1">
                  <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: `${systemStatus.progress}%` }} />
                </div>
              )}
            </div>
          </div>
        )}

        {/* ═══ UNIFIED ENTRIES LIST (sort key TBD pending backtest) ═══ */}
        {(() => {
          // /scan/combined is the canonical source post-V3.2 enrichment.
          // Sort key is currently EV — TBD after composite vs EV backtest.
          type UnifiedEntry = {
            ticker: string;
            price: number;
            composite: number;
            ev: number;
            wr: number;
            trades: number;
            avgRet: number;
            type: "FRESH_ENTRY" | "BREAKOUT" | "BOTH";
            typeLabel: string;
            rsi: number;
            sentiment?: string;
            analyst?: string;
            volumeRatio?: number;
            vetoed?: boolean;
            vetoReason?: string;
            isMR: boolean;
            qualityTier?: string;
            priceIsLive?: boolean;
          };

          const unified: UnifiedEntry[] = [];

          // Defensive filter — backend already drops vetoed in /scan/combined,
          // but we never want a vetoed signal slipping into the list.
          // V3.5 (2026-06-18): sort by `composite_score`, NOT Buffered WR.
          // Head-to-head point-in-time walk-forward (299 anchors, 7,172 PROD-gated
          // signals, 2017-2026, Fixed60d forward return) showed composite is the
          // better SORT KEY at the picks we actually trade:
          //   top-1 fwd:  Composite +4.02% vs BWR +1.03%   (OOS +5.76% vs +2.06%)
          //   top-3 fwd:  Composite +4.43% vs BWR +2.79%   (OOS +5.77% vs +3.56%)
          //   top-5 fwd:  Composite +4.07% vs BWR +2.51%   (paired t=+2.15)
          // BWR's prior "+11.50% vs EV-classic" win was vs EV (already dropped from
          // composite) — never vs composite. Sorting by composite also makes the
          // headline number + tier badge agree (they both derive from composite).
          // BWR is retained as the tiebreaker + a secondary stat.
          for (const sig of combined) {
            if (sig.vetoed) continue;
            const isFresh = sig.strategy === "MEAN_REVERSION" || sig.strategy === "BOTH";
            unified.push({
              ticker: sig.ticker,
              price: sig.price,
              composite: (sig as unknown as { composite_score?: number }).composite_score ?? 0,
              ev: sig.score,  // Buffered WR (bwr - std/sqrt(n)) — tiebreaker + secondary stat
              wr: sig.confidence,
              trades: sig.trades,
              avgRet: sig.expected_return,
              type: isFresh ? (sig.strategy === "BOTH" ? "BOTH" : "FRESH_ENTRY") : "BREAKOUT",
              typeLabel: sig.strategy_label,
              rsi: sig.rsi2 ?? 0,
              sentiment: sig.sentiment_label,
              analyst: sig.analyst_consensus,
              volumeRatio: sig.volume_ratio,
              isMR: sig.strategy !== "MOMENTUM",
              qualityTier: (sig as unknown as { quality_tier?: string }).quality_tier,
              priceIsLive: (sig as unknown as { price_is_live?: boolean }).price_is_live,
            });
          }

          // V3.5: sort by composite_score (better forward-return ranker per
          // 2017-2026 walk-forward), tiebreak by Buffered WR.
          unified.sort((a, b) => b.composite - a.composite || b.ev - a.ev);

          const freshCount = unified.filter((u) => u.type === "FRESH_ENTRY" || u.type === "BOTH").length;
          const breakoutCount = unified.filter((u) => u.type === "BREAKOUT").length;

          return (
            <>
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-amber-400" />
                <h3 className="text-sm font-semibold text-neutral-200">
                  Entry Signals ({unified.length})
                </h3>
                <span className="text-xs text-neutral-500">
                  {freshCount > 0 && <><span className="text-emerald-400 font-medium">{freshCount} fresh entries</span> · </>}
                  {breakoutCount} breakouts
                </span>
              </div>

              {unified.length === 0 ? (
                <div className={cn(
                  "rounded-xl border p-6 text-center",
                  combinedError ? "border-signal-sell/40 bg-signal-sell/5" : "border-neutral-800 bg-neutral-900/50"
                )}>
                  {combinedError ? (
                    <>
                      <p className="text-signal-sell text-sm font-medium">Couldn&apos;t load entry signals</p>
                      <p className="text-xs text-neutral-400 mt-1 font-mono">{combinedError}</p>
                      <p className="text-xs text-neutral-500 mt-2">Check the network tab — backend may be unreachable or returning an error.</p>
                    </>
                  ) : (
                    <>
                      <p className="text-neutral-400 text-sm">No entry signals right now</p>
                      <p className="text-xs text-neutral-500 mt-1">Scanner checks 3,000+ stocks. Refresh to scan again.</p>
                    </>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {unified.slice(0, showAll ? unified.length : 12).map((entry) => (
                    <div key={entry.ticker} className={cn(
                      "rounded-lg border p-3 space-y-2",
                      entry.type === "FRESH_ENTRY" ? "border-emerald-500/40 bg-emerald-500/5" :
                      entry.type === "BOTH" ? "border-amber-500/40 bg-amber-500/5" :
                      "border-blue-500/30 bg-blue-500/5"
                    )}>
                      {/* Header */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-neutral-100">{entry.ticker}</span>
                          <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-bold",
                            entry.type === "FRESH_ENTRY" ? "bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/30" :
                            entry.type === "BOTH" ? "bg-amber-500/20 text-amber-400" :
                            "bg-blue-500/20 text-blue-400"
                          )}>{entry.typeLabel}</span>
                        </div>
                        <span className="text-neutral-300 font-medium flex items-center gap-1">
                          {formatCurrency(entry.price)}
                          {entry.priceIsLive === false && (
                            <span title="Cached close — not a live intraday price" className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 font-normal">stale</span>
                          )}
                        </span>
                      </div>

                      {/* Metrics — V3.5: headline "Score" is composite_score (the sort
                          key + tier source). BWR (Buffered Win Rate) shown as secondary. */}
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <span className="text-neutral-500">Score</span>
                          <div className={cn("font-bold",
                            entry.composite >= 65 ? "text-emerald-400" : entry.composite >= 50 ? "text-blue-400" : entry.composite >= 35 ? "text-amber-300" : "text-neutral-300"
                          )}>{entry.composite.toFixed(0)} <span className="text-neutral-600 font-normal">· BWR {entry.ev.toFixed(0)}</span></div>
                        </div>
                        <div>
                          <span className="text-neutral-500">WR</span>
                          <div className={cn("font-medium", entry.wr >= 65 ? "text-signal-buy" : entry.wr >= 55 ? "text-neutral-200" : "text-signal-sell")}>
                            {entry.wr.toFixed(0)}% <span className="text-neutral-600">({entry.trades}t)</span>
                          </div>
                        </div>
                        <div>
                          <span className="text-neutral-500">Avg Ret</span>
                          <div className={cn("font-medium", pnlColor(entry.avgRet))}>
                            {entry.avgRet > 0 ? "+" : ""}{entry.avgRet.toFixed(1)}%
                          </div>
                        </div>
                      </div>

                      {/* Analyst + Sentiment + Quality tier badges */}
                      <div className="flex items-center gap-2 pt-1 border-t border-neutral-800/50 text-[10px]">
                        {entry.qualityTier && (
                          <span className={cn("px-1.5 py-0.5 rounded font-semibold",
                            entry.qualityTier === "BEST" ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30" :
                            entry.qualityTier === "GOOD" ? "bg-blue-500/15 text-blue-300" :
                            entry.qualityTier === "FAIR" ? "bg-amber-500/15 text-amber-300" :
                            "bg-neutral-800 text-neutral-400"
                          )}>{entry.qualityTier}</span>
                        )}
                        {entry.analyst && <span className="px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400">{entry.analyst}</span>}
                        {entry.sentiment && <span className={cn("px-1.5 py-0.5 rounded",
                          entry.sentiment === "POSITIVE" ? "bg-emerald-500/10 text-emerald-400" :
                          entry.sentiment === "NEGATIVE" ? "bg-red-500/10 text-red-400" :
                          "bg-neutral-800 text-neutral-400"
                        )}>{entry.sentiment}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {unified.length > 12 && !showAll && (
                <button
                  onClick={() => setShowAll(true)}
                  className="flex items-center gap-1.5 mx-auto px-4 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm transition-colors"
                >
                  <ChevronDown className="h-4 w-4" />
                  Show all {unified.length} entries
                </button>
              )}
            </>
          );
        })()}

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
            {(opp.bayesian_wr || opp.win_rate).toFixed(1)}%
            {(opp.bayesian_wr ?? 0) > 0 && Math.abs((opp.bayesian_wr ?? 0) - opp.win_rate) >= 2 && (
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
