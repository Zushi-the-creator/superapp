"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { KPICards } from "./KPICards";
import { PositionsTable } from "./PositionsTable";
import { AllocationChart } from "./AllocationChart";
import { StockSearch } from "./StockSearch";
import { AlertSettings } from "./AlertSettings";
import { ScoreGauge } from "@/components/shared/ScoreGauge";
import { RegimeBadge, SignalBadge } from "@/components/shared/Badges";
import { Sparkline } from "@/components/shared/Sparkline";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { api } from "@/lib/api";
import { ArrowUp, ArrowRightLeft, TrendingUp, Loader2, CheckCircle2, XCircle, Newspaper, ChevronDown } from "lucide-react";
import { useState } from "react";
import type { ScanOpportunity, StockAnalysis } from "@/lib/types";

export function PortfolioTab() {
  const { portfolio, scanner } = useData();
  const { data, loading, lastUpdated, refresh } = portfolio;

  const upgrades = (scanner.data?.opportunities ?? []).filter(
    (o) => o.is_upgrade && !o.vetoed
  );

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Portfolio"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        <KPICards summary={data?.summary ?? null} loading={loading && !data} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <PositionsTable
              positions={data?.positions ?? []}
              loading={loading && !data}
            />
          </div>
          <div>
            <AllocationChart positions={data?.positions ?? []} />
          </div>
        </div>

        {/* Stock Search + Alert Settings */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <h3 className="text-sm font-semibold text-neutral-200 mb-3">Analyze Stock</h3>
            <StockSearch />
          </div>
          <div>
            <AlertSettings />
          </div>
        </div>

        {/* Upgrade Suggestions from Scanner */}
        <UpgradeSuggestions
          upgrades={upgrades}
          scannerLoading={scanner.loading && !scanner.data}
          totalScanned={scanner.data?.total_scanned ?? 0}
          lastScan={scanner.lastUpdated}
        />
      </div>
    </div>
  );
}

function UpgradeSuggestions({
  upgrades,
  scannerLoading,
  totalScanned,
  lastScan,
}: {
  upgrades: ScanOpportunity[];
  scannerLoading: boolean;
  totalScanned: number;
  lastScan: Date | null;
}) {
  if (scannerLoading) {
    return (
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-6">
        <div className="flex items-center gap-2 mb-3">
          <ArrowRightLeft className="h-4 w-4 text-neutral-500 animate-pulse" />
          <span className="text-sm text-neutral-500">
            Scanning for better stocks...
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-32 rounded-xl border border-neutral-800 bg-neutral-900/30 animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4 text-signal-buy" />
          <h3 className="text-sm font-semibold text-neutral-200">
            Potential Upgrades
          </h3>
          {upgrades.length > 0 && (
            <span className="px-1.5 py-0.5 rounded bg-signal-buy/15 text-signal-buy text-xs font-medium">
              {upgrades.length}
            </span>
          )}
        </div>
        <span className="text-[10px] text-neutral-600">
          {totalScanned.toLocaleString()} scanned
          {lastScan && ` · ${lastScan.toLocaleTimeString()}`}
        </span>
      </div>

      {upgrades.length === 0 ? (
        <div className="flex items-center gap-2 py-3 px-4 rounded-lg bg-signal-buy/5 border border-signal-buy/20">
          <TrendingUp className="h-4 w-4 text-signal-buy" />
          <span className="text-sm text-signal-buy font-medium">
            {totalScanned === 0
              ? "Waiting for scan results..."
              : "Portfolio is optimal — no stock outperforms current holdings"}
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {upgrades.map((opp) => (
            <UpgradeCard key={opp.ticker} opp={opp} />
          ))}
        </div>
      )}
    </div>
  );
}

function UpgradeCard({ opp }: { opp: ScanOpportunity }) {
  const [expanded, setExpanded] = useState(false);
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (analysis) return; // already fetched
    setLoadingDetail(true);
    setError(null);
    try {
      const data = await api.analyzeStock(opp.ticker);
      setAnalysis(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border bg-signal-buy/5 p-3 transition-colors cursor-pointer",
        expanded ? "border-signal-buy/60 col-span-1 md:col-span-2 xl:col-span-3" : "border-signal-buy/30 hover:border-signal-buy/50"
      )}
      onClick={handleClick}
    >
      {/* Beats badge */}
      <div className="flex items-center gap-1.5 mb-2">
        <ArrowUp className="h-3 w-3 text-signal-buy" />
        <span className="text-[10px] font-medium text-signal-buy">
          REPLACES {opp.beats_holdings.join(", ")}
        </span>
        <ChevronDown className={cn("h-3 w-3 text-neutral-500 ml-auto transition-transform", expanded && "rotate-180")} />
      </div>

      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-neutral-100">{opp.ticker}</span>
            <RegimeBadge regime={opp.regime} />
          </div>
          <span className="text-xs text-neutral-400">
            {formatCurrency(opp.price)}
          </span>
        </div>
        <ScoreGauge value={opp.win_rate} size={44} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-neutral-500">Zone Ret</span>
          <div className={cn("font-medium", pnlColor(opp.zone_return))}>
            {formatPercent(opp.zone_return)}
          </div>
        </div>
        <div>
          <span className="text-neutral-500">WR</span>
          <div className="text-neutral-200 font-medium">
            {opp.win_rate.toFixed(0)}%
          </div>
        </div>
        <div>
          <span className="text-neutral-500">Score</span>
          <div className="text-signal-buy font-medium">
            {opp.score.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Analyst + Sentiment */}
      <div className="flex items-center gap-2 mt-2 text-xs">
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
        <span className="ml-auto text-neutral-500">{opp.trades} trades</span>
      </div>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-signal-buy/20" onClick={(e) => e.stopPropagation()}>
          {loadingDetail && (
            <div className="flex items-center gap-2 py-4 justify-center text-neutral-400 text-xs">
              <Loader2 className="h-4 w-4 animate-spin" />
              Fetching live analysis...
            </div>
          )}
          {error && (
            <div className="text-signal-sell text-xs py-2">{error}</div>
          )}
          {analysis && <UpgradeDetail analysis={analysis} opp={opp} />}
        </div>
      )}
    </div>
  );
}

function CheckRow({ passed, label }: { passed: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {passed ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-signal-buy shrink-0" />
      ) : (
        <XCircle className="h-3.5 w-3.5 text-signal-sell shrink-0" />
      )}
      <span className={passed ? "text-neutral-300" : "text-signal-sell"}>{label}</span>
    </div>
  );
}

function UpgradeDetail({ analysis, opp }: { analysis: StockAnalysis; opp: ScanOpportunity }) {
  const a = analysis;

  const modelPassed = a.win_rate >= 55 && a.total_trades >= 10 && a.above_sma50;
  const sentimentOk = a.sentiment_label !== "NEGATIVE";
  const earningsOk = !a.earnings_date;
  const allPassed = modelPassed && sentimentOk && earningsOk;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Column 1: Live data + model checks */}
      <div className="space-y-3">
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Live Data</div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-bold text-neutral-100">{formatCurrency(a.live_price)}</span>
            <span className={cn("text-xs font-medium", pnlColor(a.day_change_pct))}>
              {a.day_change_pct >= 0 ? "+" : ""}{a.day_change_pct.toFixed(2)}%
            </span>
          </div>
          {a.sparkline.length > 0 && (
            <div className="mt-1.5">
              <Sparkline data={a.sparkline} />
            </div>
          )}
        </div>
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Model Validation</div>
          <div className="space-y-1">
            <CheckRow passed={a.above_sma50} label={`Price > SMA50 (${formatCurrency(a.sma50)})`} />
            <CheckRow passed={a.rsi2 < 30} label={`RSI(2) = ${a.rsi2.toFixed(1)} ${a.rsi2 < 20 ? "(oversold)" : a.rsi2 < 30 ? "(low)" : ""}`} />
            <CheckRow passed={a.win_rate >= 55} label={`Win Rate: ${a.win_rate.toFixed(1)}% (${a.total_trades} trades)`} />
            <CheckRow passed={a.exit_zone_return > 0} label={`Zone Return: ${formatPercent(a.exit_zone_return)} at RSI ${a.rsi_zone}`} />
          </div>
        </div>
      </div>

      {/* Column 2: Sentiment + Analyst + Earnings */}
      <div className="space-y-3">
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Sentiment</div>
          <CheckRow passed={sentimentOk} label={`${a.sentiment_label} (score: ${a.sentiment_score.toFixed(2)})`} />
        </div>
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Analyst</div>
          <div className="space-y-1">
            <CheckRow passed={["Strong Buy", "Buy"].includes(a.analyst_consensus)} label={`Consensus: ${a.analyst_consensus}`} />
            {a.analyst_target > 0 && (
              <CheckRow
                passed={a.analyst_upside > 0}
                label={`Target: ${formatCurrency(a.analyst_target)} (${a.analyst_upside > 0 ? "+" : ""}${a.analyst_upside.toFixed(1)}% upside)`}
              />
            )}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Earnings</div>
          <CheckRow
            passed={earningsOk}
            label={a.earnings_date ? `Earnings: ${a.earnings_date} — CAUTION` : "No upcoming earnings — clear"}
          />
        </div>
        {a.issues.length > 0 && (
          <div>
            <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Issues</div>
            <div className="space-y-0.5">
              {a.issues.map((issue, i) => (
                <div key={i} className="text-xs text-signal-sell">{issue}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Column 3: Why buy + news */}
      <div className="space-y-3">
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Signal</div>
          <div className="flex items-center gap-2">
            <SignalBadge signal={a.signal} />
            <span className={cn(
              "text-xs font-bold",
              allPassed ? "text-signal-buy" : "text-amber-400"
            )}>
              {allPassed ? "ALL CHECKS PASSED" : "HAS WARNINGS"}
            </span>
          </div>
        </div>
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1.5">Why Buy</div>
          <p className="text-xs text-neutral-300 leading-relaxed">
            {opp.ticker} scores <span className="text-signal-buy font-medium">{a.score.toFixed(2)}</span> —{" "}
            {a.win_rate.toFixed(0)}% win rate over {a.total_trades} trades with{" "}
            <span className={cn("font-medium", pnlColor(a.exit_zone_return))}>{formatPercent(a.exit_zone_return)}</span>{" "}
            expected return at current RSI zone.
            {a.analyst_upside > 0 && ` Analysts see ${a.analyst_upside.toFixed(0)}% upside to ${formatCurrency(a.analyst_target)}.`}
            {` Replaces ${opp.beats_holdings.join(", ")} for better risk/reward.`}
          </p>
        </div>
        {a.headlines.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-1">
              <Newspaper className="h-3 w-3 text-neutral-500" />
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Latest News</span>
            </div>
            <p className="text-xs text-neutral-400 leading-relaxed line-clamp-2">
              {a.headlines[0]}
            </p>
          </div>
        )}
        {/* Exit strategy */}
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Exit Plan</div>
          <div className="flex gap-3 text-xs">
            <div>
              <span className="text-neutral-500">Stop</span>
              <div className="text-signal-sell font-medium">{formatCurrency(a.stop_loss)}</div>
            </div>
            <div>
              <span className="text-neutral-500">Target 1</span>
              <div className="text-signal-buy font-medium">{formatCurrency(a.target_1)}</div>
            </div>
            <div>
              <span className="text-neutral-500">Target 2</span>
              <div className="text-signal-buy font-medium">{formatCurrency(a.target_2)}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
