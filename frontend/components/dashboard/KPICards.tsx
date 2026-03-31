"use client";

import { DollarSign, TrendingUp, Calendar, Layers, Target, Banknote, Activity, HeartPulse } from "lucide-react";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import type { PortfolioSummary, MarketRegime, StrategyHealth } from "@/lib/types";
import { CardSkeleton } from "@/components/shared/Skeleton";

export function KPICards({
  summary,
  loading,
  marketRegime,
  strategyHealth,
}: {
  summary: PortfolioSummary | null;
  loading: boolean;
  marketRegime?: MarketRegime | null;
  strategyHealth?: StrategyHealth | null;
}) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  // Total P&L = realized + unrealized - all fees (commissions + broker tax)
  const totalPnl = (summary.realized_pnl ?? 0) + summary.total_pnl - summary.total_fees;
  const totalPnlPct = (summary.total_deposited ?? 0) > 0
    ? (totalPnl / summary.total_deposited) * 100 : 0;

  const cards = [
    {
      label: "Total P&L",
      value: `${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(1)}%`,
      sub: formatCurrency(totalPnl),
      icon: TrendingUp,
      color: pnlColor(totalPnlPct),
      bg: totalPnlPct >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Portfolio Value",
      value: formatCurrency(summary.total_value),
      sub: `Cash: ${formatCurrency(summary.cash ?? 0)} · ${formatCurrency(summary.total_deposited ?? 0)} invested`,
      icon: DollarSign,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
    {
      label: "Today's P&L",
      value: `${formatCurrency(summary.day_pnl)} (${summary.day_pnl_pct >= 0 ? "+" : ""}${summary.day_pnl_pct.toFixed(2)}%)`,
      icon: Calendar,
      color: pnlColor(summary.day_pnl),
      bg: summary.day_pnl >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Realized P&L",
      value: `${formatCurrency(summary.realized_pnl ?? 0)}`,
      sub: `Fees: ${formatCurrency(summary.total_fees)}`,
      icon: Banknote,
      color: pnlColor(summary.realized_pnl ?? 0),
      bg: (summary.realized_pnl ?? 0) >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: `${summary.position_count} Positions`,
      value: `Adj. WR ${summary.avg_win_rate.toFixed(0)}%`,
      icon: Target,
      color: summary.avg_win_rate >= 80 ? "text-signal-buy" : summary.avg_win_rate >= 65 ? "text-amber-400" : "text-signal-sell",
      bg: summary.avg_win_rate >= 80 ? "bg-signal-buy/10" : summary.avg_win_rate >= 65 ? "bg-amber-500/10" : "bg-signal-sell/10",
    },
  ];

  // VIX regime card
  const regime = marketRegime;
  const regimeColor = !regime || regime.regime === "UNKNOWN"
    ? "text-neutral-400"
    : regime.regime === "HEALTHY"
    ? "text-signal-buy"
    : regime.regime === "CAUTION"
    ? "text-amber-400"
    : "text-signal-sell";
  const regimeBg = !regime || regime.regime === "UNKNOWN"
    ? "bg-neutral-700/10"
    : regime.regime === "HEALTHY"
    ? "bg-signal-buy/10"
    : regime.regime === "CAUTION"
    ? "bg-amber-500/10"
    : "bg-signal-sell/10";
  const regimeLabel = regime
    ? regime.regime === "BEAR"
      ? `SPY < SMA200 — BEAR MARKET`
      : regime.regime === "CRISIS"
      ? `VIX ${regime.vix} — PAUSED`
      : regime.regime === "DECLINING"
      ? `SPY ${regime.spy_5d_return >= 0 ? "+" : ""}${regime.spy_5d_return.toFixed(1)}% — ENTRIES PAUSED`
      : regime.regime === "FEAR"
      ? `VIX ${regime.vix} — ${regime.position_size_pct}% Size`
      : regime.regime === "CAUTION"
      ? `VIX ${regime.vix} — ${regime.position_size_pct}% Size`
      : regime.regime === "HEALTHY"
      ? `VIX ${regime.vix} — Full Size`
      : `VIX ${regime.vix}`
    : "No Data";

  return (
    <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className={cn(
            "rounded-xl border border-neutral-800 p-4",
            card.bg
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            <card.icon className={cn("h-4 w-4", card.color)} />
            <span className="text-xs text-neutral-400">{card.label}</span>
          </div>
          <div className={cn("text-lg font-semibold", card.color)}>
            {card.value}
          </div>
          {"sub" in card && card.sub && (
            <div className="text-[10px] text-neutral-500 mt-0.5">{card.sub}</div>
          )}
        </div>
      ))}
      {/* VIX Regime Card */}
      <div
        className={cn(
          "rounded-xl border border-neutral-800 p-4",
          regimeBg,
          regime?.regime === "CRISIS" && "animate-pulse"
        )}
      >
        <div className="flex items-center gap-2 mb-2">
          <Activity className={cn("h-4 w-4", regimeColor)} />
          <span className="text-xs text-neutral-400">Market Regime</span>
        </div>
        <div className={cn("text-lg font-semibold", regimeColor)}>
          {regimeLabel}
        </div>
        {regime && (
          <div className="text-[10px] text-neutral-500 mt-0.5">
            SPY 5d: {regime.spy_5d_return >= 0 ? "+" : ""}{regime.spy_5d_return.toFixed(1)}%
            {regime.pause_entries && " · Entries paused"}
          </div>
        )}
      </div>
      {/* Strategy Health Card */}
      <div
        className={cn(
          "rounded-xl border border-neutral-800 p-4",
          !strategyHealth || strategyHealth.status === "INSUFFICIENT"
            ? "bg-neutral-700/10"
            : strategyHealth.status === "OUTPERFORMING"
            ? "bg-signal-buy/10"
            : strategyHealth.status === "HEALTHY"
            ? "bg-signal-buy/10"
            : strategyHealth.status === "WARNING"
            ? "bg-amber-500/10"
            : "bg-signal-sell/10",
          strategyHealth?.status === "DEGRADED" && "animate-pulse"
        )}
      >
        <div className="flex items-center gap-2 mb-2">
          <HeartPulse className={cn("h-4 w-4",
            !strategyHealth || strategyHealth.status === "INSUFFICIENT"
              ? "text-neutral-400"
              : strategyHealth.status === "OUTPERFORMING"
              ? "text-emerald-400"
              : strategyHealth.status === "HEALTHY"
              ? "text-signal-buy"
              : strategyHealth.status === "WARNING"
              ? "text-amber-400"
              : "text-signal-sell"
          )} />
          <span className="text-xs text-neutral-400">Strategy Health</span>
        </div>
        <div className={cn("text-lg font-semibold",
          !strategyHealth || strategyHealth.status === "INSUFFICIENT"
            ? "text-neutral-400"
            : strategyHealth.status === "OUTPERFORMING"
            ? "text-emerald-400"
            : strategyHealth.status === "HEALTHY"
            ? "text-signal-buy"
            : strategyHealth.status === "WARNING"
            ? "text-amber-400"
            : "text-signal-sell"
        )}>
          {!strategyHealth || strategyHealth.status === "INSUFFICIENT"
            ? "No Data"
            : strategyHealth.status === "OUTPERFORMING"
            ? `Strong — WR ${strategyHealth.rolling_wr.toFixed(0)}%`
            : strategyHealth.status === "HEALTHY"
            ? `Strategy OK — WR ${strategyHealth.rolling_wr.toFixed(0)}%`
            : strategyHealth.status === "WARNING"
            ? `Watch — WR ${strategyHealth.rolling_wr.toFixed(0)}%`
            : `DEGRADED — WR ${strategyHealth.rolling_wr.toFixed(0)}%`}
        </div>
        {strategyHealth && strategyHealth.status !== "INSUFFICIENT" && (
          <div className="text-[10px] text-neutral-500 mt-0.5">
            {strategyHealth.trades_analyzed} trades · Expected {strategyHealth.expected_wr}% · Gap {strategyHealth.gap_pp > 0 ? "+" : ""}{strategyHealth.gap_pp}pp
          </div>
        )}
      </div>
    </div>
  );
}
