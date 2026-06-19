"use client";

import { DollarSign, TrendingUp, Calendar, Banknote, Activity, ArrowLeftRight, Clock } from "lucide-react";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import type { PortfolioSummary, MarketRegime } from "@/lib/types";
import { CardSkeleton } from "@/components/shared/Skeleton";

export function KPICards({
  summary,
  loading,
  marketRegime,
}: {
  summary: PortfolioSummary | null;
  loading: boolean;
  marketRegime?: MarketRegime | null;
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

  // Total P&L = current portfolio value (positions + cash) − everything deposited.
  // This is the ground truth: it implicitly accounts for realized + unrealized − fees − tax,
  // and stays correct regardless of how those flows get accounted for in the ledger.
  const totalPnl = summary.total_value - (summary.total_deposited ?? 0);
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
      label: "Today",
      value: `${formatCurrency(summary.day_pnl)} (${summary.day_pnl_pct >= 0 ? "+" : ""}${summary.day_pnl_pct.toFixed(2)}%)`,
      icon: Clock,
      color: pnlColor(summary.day_pnl),
      bg: summary.day_pnl >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Yesterday",
      value: `${(summary.yesterday_pnl ?? 0) >= 0 ? "+" : ""}${formatCurrency(summary.yesterday_pnl ?? 0)}`,
      sub: `${(summary.yesterday_pnl_pct ?? 0) >= 0 ? "+" : ""}${(summary.yesterday_pnl_pct ?? 0).toFixed(2)}%`,
      icon: Calendar,
      color: pnlColor(summary.yesterday_pnl ?? 0),
      bg: (summary.yesterday_pnl ?? 0) >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Last 7 Days",
      value: `${(summary.week_pnl ?? 0) >= 0 ? "+" : ""}${formatCurrency(summary.week_pnl ?? 0)}`,
      sub: `${(summary.week_pnl_pct ?? 0) >= 0 ? "+" : ""}${(summary.week_pnl_pct ?? 0).toFixed(2)}%`,
      icon: ArrowLeftRight,
      color: pnlColor(summary.week_pnl ?? 0),
      bg: (summary.week_pnl ?? 0) >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      // Gross profit = portfolio value − total deposited.
      // Equivalent to realized + unrealized − fees − tax (within rounding noise).
      // This is the bottom-line "what did I actually make" number.
      label: "Gross Profit",
      value: formatCurrency(totalPnl),
      sub: `Closed: ${formatCurrency(summary.realized_pnl ?? 0)} · Open: ${formatCurrency(summary.total_pnl)} · Fees ${formatCurrency(-summary.total_fees)} · Tax ${formatCurrency(-(summary.total_tax ?? 0))}`,
      icon: Banknote,
      color: pnlColor(totalPnl),
      bg: totalPnl >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
  ];

  // VIX regime card
  const regime = marketRegime;
  // Drive color/label off the backend's actual fields (pause_entries,
  // position_size_pct) and the emitted regime NAME — not a hardcoded list of
  // regime strings, several of which (BEAR/DECLINING/CAUTION) the backend never
  // emits, so DANGER/CRISIS previously showed no "PAUSED" warning (2026-06-19 fix).
  const _sizePct = regime?.position_size_pct ?? 100;
  const _spy5d = regime?.spy_5d_return ?? 0;
  const regimeColor = !regime || regime.regime === "UNKNOWN"
    ? "text-neutral-400"
    : regime.pause_entries
    ? "text-signal-sell"
    : _sizePct < 100
    ? "text-amber-400"
    : "text-signal-buy";
  const regimeBg = !regime || regime.regime === "UNKNOWN"
    ? "bg-neutral-700/10"
    : regime.pause_entries
    ? "bg-signal-sell/10"
    : _sizePct < 100
    ? "bg-amber-500/10"
    : "bg-signal-buy/10";
  const regimeLabel = !regime || regime.regime === "UNKNOWN"
    ? "No Data"
    : regime.pause_entries
    ? `${regime.regime} — ENTRIES PAUSED`
    : _sizePct < 100
    ? `${regime.regime} — ${_sizePct}% Size`
    : `${regime.regime} — Full Size`;

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
            SPY 5d: {_spy5d >= 0 ? "+" : ""}{_spy5d.toFixed(1)}%
            {regime.pause_entries && " · Entries paused"}
          </div>
        )}
      </div>
    </div>
  );
}
