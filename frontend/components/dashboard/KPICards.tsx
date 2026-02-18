"use client";

import { DollarSign, TrendingUp, Calendar, Layers, Target } from "lucide-react";
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

  const cards = [
    {
      label: "Portfolio Value",
      value: formatCurrency(summary.total_value),
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
      label: "Total P&L",
      value: `${formatCurrency(summary.total_pnl)} (${formatPercent(summary.total_pnl_pct)})`,
      icon: TrendingUp,
      color: pnlColor(summary.total_pnl),
      bg: summary.total_pnl >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Positions",
      value: summary.position_count.toString(),
      icon: Layers,
      color: "text-neutral-200",
      bg: "bg-neutral-700/30",
    },
    {
      label: "Avg Win Rate",
      value: `${summary.avg_win_rate.toFixed(1)}%`,
      icon: Target,
      color: summary.avg_win_rate >= 70 ? "text-signal-buy" : summary.avg_win_rate >= 55 ? "text-amber-400" : "text-signal-sell",
      bg: summary.avg_win_rate >= 70 ? "bg-signal-buy/10" : summary.avg_win_rate >= 55 ? "bg-amber-500/10" : "bg-signal-sell/10",
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
        </div>
      ))}
    </div>
  );
}
