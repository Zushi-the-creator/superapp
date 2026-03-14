"use client";

import { DollarSign, TrendingUp, Calendar, Layers, Target, Banknote } from "lucide-react";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import type { PortfolioSummary } from "@/lib/types";
import { CardSkeleton } from "@/components/shared/Skeleton";

export function KPICards({
  summary,
  loading,
}: {
  summary: PortfolioSummary | null;
  loading: boolean;
}) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
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

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
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
    </div>
  );
}
