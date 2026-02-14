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
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { ArrowUp, ArrowRightLeft, TrendingUp } from "lucide-react";
import type { ScanOpportunity } from "@/lib/types";

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
          {upgrades.slice(0, 6).map((opp) => (
            <UpgradeCard key={opp.ticker} opp={opp} />
          ))}
        </div>
      )}
    </div>
  );
}

function UpgradeCard({ opp }: { opp: ScanOpportunity }) {
  return (
    <div className="rounded-xl border border-signal-buy/30 bg-signal-buy/5 p-3 hover:border-signal-buy/50 transition-colors">
      {/* Beats badge */}
      <div className="flex items-center gap-1.5 mb-2">
        <ArrowUp className="h-3 w-3 text-signal-buy" />
        <span className="text-[10px] font-medium text-signal-buy">
          REPLACES {opp.beats_holdings.join(", ")}
        </span>
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
    </div>
  );
}
