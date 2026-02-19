"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { LivePulse } from "@/components/shared/LivePulse";
import { SignalBadge, RegimeBadge, TierBadge, HealthBadge } from "@/components/shared/Badges";
import { Sparkline } from "@/components/shared/Sparkline";
import { CardSkeleton, TableSkeleton } from "@/components/shared/Skeleton";
import { formatILS, formatPercent, cn, pnlColor } from "@/lib/utils";
import type { PortfolioSummary, PositionDetail } from "@/lib/types";
import { DollarSign, TrendingUp, Calendar, Layers, Target } from "lucide-react";

export function ILSPortfolioTab() {
  const { portfolioILS } = useData();
  const { data, loading, lastUpdated, refresh } = portfolioILS;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="ILS Portfolio"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        <ILSKPICards summary={data?.summary ?? null} loading={loading && !data} />
        <ILSPositionsTable
          positions={data?.positions ?? []}
          loading={loading && !data}
        />
      </div>
    </div>
  );
}

function ILSKPICards({
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
      value: formatILS(summary.total_value),
      icon: DollarSign,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
    {
      label: "Today's P&L",
      value: `${formatILS(summary.day_pnl)} (${summary.day_pnl_pct >= 0 ? "+" : ""}${summary.day_pnl_pct.toFixed(2)}%)`,
      icon: Calendar,
      color: pnlColor(summary.day_pnl),
      bg: summary.day_pnl >= 0 ? "bg-signal-buy/10" : "bg-signal-sell/10",
    },
    {
      label: "Total P&L",
      value: `${formatILS(summary.total_pnl)} (${formatPercent(summary.total_pnl_pct)})`,
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
      color:
        summary.avg_win_rate >= 70
          ? "text-signal-buy"
          : summary.avg_win_rate >= 55
          ? "text-amber-400"
          : "text-signal-sell",
      bg:
        summary.avg_win_rate >= 70
          ? "bg-signal-buy/10"
          : summary.avg_win_rate >= 55
          ? "bg-amber-500/10"
          : "bg-signal-sell/10",
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

function ILSPositionsTable({
  positions,
  loading,
}: {
  positions: PositionDetail[];
  loading: boolean;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (loading) return <TableSkeleton rows={3} />;

  if (positions.length === 0) {
    return (
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-8 text-center">
        <p className="text-neutral-400 text-sm">No ILS positions yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-neutral-800 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-800 bg-neutral-900/50">
            <th className="text-left px-4 py-3 text-xs text-neutral-500 font-medium">Ticker</th>
            <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">Entry</th>
            <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">Live</th>
            <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">P&L</th>
            <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Weight</th>
            <th className="text-center px-3 py-3 text-xs text-neutral-500 font-medium hidden lg:table-cell">20d</th>
            <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Exit Strategy</th>
            <th className="text-center px-3 py-3 text-xs text-neutral-500 font-medium">Signal</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <ILSPositionRow
              key={pos.id}
              pos={pos}
              isExpanded={expanded === pos.id}
              onToggle={() =>
                setExpanded(expanded === pos.id ? null : pos.id)
              }
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ILSPositionRow({
  pos,
  isExpanded,
  onToggle,
}: {
  pos: PositionDetail;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className="border-b border-neutral-800/50 hover:bg-neutral-800/30 transition-colors cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <HealthBadge issues={pos.issues} />
            <span className="font-medium text-neutral-100">{pos.ticker}</span>
            <TierBadge tier={pos.tier} />
          </div>
        </td>
        <td className="text-right px-3 py-3 text-neutral-400">
          {formatILS(pos.entry_price)}
        </td>
        <td className="text-right px-3 py-3">
          <div className="flex items-center justify-end gap-1.5">
            <span className="text-neutral-100 font-medium">
              {formatILS(pos.current_price)}
            </span>
            <LivePulse positive={pos.day_change_pct >= 0} />
          </div>
          <span className={cn("text-xs", pnlColor(pos.day_change_pct))}>
            {formatPercent(pos.day_change_pct)}
          </span>
        </td>
        <td className={cn("text-right px-3 py-3 font-medium", pnlColor(pos.pnl))}>
          <div>{formatILS(pos.pnl)}</div>
          <span className="text-xs">{formatPercent(pos.pnl_pct)}</span>
        </td>
        <td className="text-right px-3 py-3 text-neutral-400 hidden md:table-cell">
          {pos.weight.toFixed(1)}%
        </td>
        <td className="text-center px-3 py-3 hidden lg:table-cell">
          <Sparkline data={pos.sparkline} />
        </td>
        <td className="text-right px-3 py-3 hidden md:table-cell">
          {pos.exit_strategy ? (
            <div>
              <span
                className={cn(
                  "font-medium text-xs",
                  pos.exit_triggered
                    ? "text-signal-sell animate-pulse"
                    : "text-amber-400"
                )}
              >
                {pos.exit_strategy}
              </span>
              {pos.exit_price > 0 ? (
                <div
                  className={cn(
                    "text-[10px]",
                    pos.exit_triggered ? "text-signal-sell" : "text-neutral-500"
                  )}
                >
                  {formatILS(pos.exit_price)}
                </div>
              ) : pos.exit_triggered && pos.exit_strategy?.startsWith("RSI") ? (
                <div className="text-[10px] text-signal-sell">
                  RSI {pos.rsi2?.toFixed(0)}
                </div>
              ) : null}
            </div>
          ) : (
            <span className="text-neutral-600 text-xs">—</span>
          )}
        </td>
        <td className="text-center px-3 py-3">
          <SignalBadge signal={pos.signal || "HOLD"} />
        </td>
        <td className="px-2">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-neutral-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-neutral-500" />
          )}
        </td>
      </tr>

      {isExpanded && (
        <tr className="bg-neutral-900/30">
          <td colSpan={9} className="px-4 py-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
              <div>
                <span className="text-neutral-500">RSI(2)</span>
                <div className="text-neutral-200 font-medium">
                  {pos.rsi2 >= 0 ? pos.rsi2.toFixed(1) : "N/A"}
                </div>
              </div>
              <div>
                <span className="text-neutral-500">SMA50</span>
                <div
                  className={cn(
                    "font-medium",
                    pos.above_sma50 ? "text-signal-buy" : "text-signal-sell"
                  )}
                >
                  {formatILS(pos.sma50)}{" "}
                  ({pos.sma50_buffer > 0 ? `+${pos.sma50_buffer.toFixed(1)}%` : `${pos.sma50_buffer?.toFixed(1)}%`})
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Regime</span>
                <div className="flex items-center gap-1.5">
                  <RegimeBadge regime={pos.regime} />
                  <TierBadge tier={pos.tier} />
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Win Rate</span>
                <div className="text-neutral-200 font-medium">
                  {pos.win_rate.toFixed(1)}% ({pos.total_trades} trades)
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Exit Strategy</span>
                <div
                  className={cn(
                    "font-medium",
                    pos.exit_triggered
                      ? "text-signal-sell animate-pulse"
                      : "text-amber-400"
                  )}
                >
                  {pos.exit_strategy || "—"}
                </div>
                {pos.exit_label && (
                  <div className="text-[10px] mt-0.5 text-neutral-400">
                    {pos.exit_label}
                  </div>
                )}
              </div>
              <div>
                <span className="text-neutral-500">
                  Zone Return (RSI {pos.rsi_zone})
                </span>
                <div className={cn("font-medium", pnlColor(pos.exit_zone_return))}>
                  {formatPercent(pos.exit_zone_return)} ({pos.exit_zone_wr?.toFixed(0)}% WR, {pos.exit_zone_trades} trades)
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Shares</span>
                <div className="text-neutral-200 font-medium">
                  {pos.shares.toFixed(0)}
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Cost Basis</span>
                <div className="text-neutral-200 font-medium">
                  {formatILS(pos.cost_basis)}
                </div>
              </div>
              {/* Stop Loss & Targets */}
              <div className="col-span-2 md:col-span-4 mt-1 pt-2 border-t border-neutral-800/50">
                <div className="grid grid-cols-4 gap-3">
                  <div>
                    <span className="text-neutral-500">Stop Loss ({pos.stop_pct}%)</span>
                    <div
                      className={cn(
                        "font-medium",
                        pos.current_price <= pos.stop_loss
                          ? "text-signal-sell animate-pulse"
                          : "text-signal-sell/60"
                      )}
                    >
                      {formatILS(pos.stop_loss)}
                    </div>
                  </div>
                  <div>
                    <span className="text-neutral-500">Exit ({pos.exit_strategy})</span>
                    {pos.exit_price > 0 ? (
                      <div
                        className={cn(
                          "font-medium",
                          pos.exit_triggered
                            ? "text-signal-sell animate-pulse"
                            : "text-amber-400/60"
                        )}
                      >
                        {formatILS(pos.exit_price)}
                      </div>
                    ) : (
                      <div className="text-neutral-600 font-medium">—</div>
                    )}
                  </div>
                  <div>
                    <span className="text-neutral-500">Target 1 (+{pos.target_1_pct}%)</span>
                    <div
                      className={cn(
                        "font-medium",
                        pos.current_price >= pos.target_1
                          ? "text-signal-buy animate-pulse"
                          : "text-signal-buy/60"
                      )}
                    >
                      {formatILS(pos.target_1)}
                    </div>
                  </div>
                  <div>
                    <span className="text-neutral-500">Target 2 (+{pos.target_2_pct}%)</span>
                    <div
                      className={cn(
                        "font-medium",
                        pos.current_price >= pos.target_2
                          ? "text-signal-buy animate-pulse"
                          : "text-signal-buy/60"
                      )}
                    >
                      {formatILS(pos.target_2)}
                    </div>
                  </div>
                </div>
              </div>
              {pos.issues.length > 0 && (
                <div className="col-span-2 md:col-span-4">
                  <span className="text-neutral-500">Issues</span>
                  <div className="text-signal-sell text-xs mt-1 space-y-0.5">
                    {pos.issues.map((issue, i) => (
                      <div key={i}>{issue}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
