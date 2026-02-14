"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { LivePulse } from "@/components/shared/LivePulse";
import { SignalBadge, RegimeBadge, HealthBadge } from "@/components/shared/Badges";
import { Sparkline } from "@/components/shared/Sparkline";
import { TableSkeleton } from "@/components/shared/Skeleton";
import type { PositionDetail } from "@/lib/types";

export function PositionsTable({
  positions,
  loading,
}: {
  positions: PositionDetail[];
  loading: boolean;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (loading) return <TableSkeleton rows={4} />;

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
            <th className="text-center px-3 py-3 text-xs text-neutral-500 font-medium">Signal</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <PositionRow
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

function PositionRow({
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
          </div>
        </td>
        <td className="text-right px-3 py-3 text-neutral-400">
          {formatCurrency(pos.entry_price)}
        </td>
        <td className="text-right px-3 py-3">
          <div className="flex items-center justify-end gap-1.5">
            <span className="text-neutral-100 font-medium">
              {formatCurrency(pos.current_price)}
            </span>
            <LivePulse positive={pos.day_change_pct >= 0} />
          </div>
          <span className={cn("text-xs", pnlColor(pos.day_change_pct))}>
            {formatPercent(pos.day_change_pct)}
          </span>
        </td>
        <td className={cn("text-right px-3 py-3 font-medium", pnlColor(pos.pnl))}>
          <div>{formatCurrency(pos.pnl)}</div>
          <span className="text-xs">{formatPercent(pos.pnl_pct)}</span>
        </td>
        <td className="text-right px-3 py-3 text-neutral-400 hidden md:table-cell">
          {pos.weight.toFixed(1)}%
        </td>
        <td className="text-center px-3 py-3 hidden lg:table-cell">
          <Sparkline data={pos.sparkline} />
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
          <td colSpan={8} className="px-4 py-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
              <div>
                <span className="text-neutral-500">RSI(2)</span>
                <div className="text-neutral-200 font-medium">
                  {pos.rsi2 >= 0 ? pos.rsi2.toFixed(1) : "N/A"}
                </div>
              </div>
              <div>
                <span className="text-neutral-500">SMA50</span>
                <div className={cn("font-medium", pos.above_sma50 ? "text-signal-buy" : "text-signal-sell")}>
                  {formatCurrency(pos.sma50)} ({pos.above_sma50 ? "ABOVE" : "BELOW"})
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Regime</span>
                <div><RegimeBadge regime={pos.regime} /></div>
              </div>
              <div>
                <span className="text-neutral-500">Win Rate</span>
                <div className="text-neutral-200 font-medium">
                  {pos.win_rate.toFixed(1)}% ({pos.total_trades} trades)
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Exit Zone Return</span>
                <div className={cn("font-medium", pnlColor(pos.exit_zone_return))}>
                  {formatPercent(pos.exit_zone_return)} ({pos.exit_zone_wr?.toFixed(0)}% WR, {pos.exit_zone_trades} trades)
                </div>
                <div className="text-neutral-600 text-[10px]">7d fwd return at RSI {pos.rsi_zone}</div>
              </div>
              <div>
                <span className="text-neutral-500">Avg Return</span>
                <div className={cn("font-medium", pnlColor(pos.avg_return))}>
                  {formatPercent(pos.avg_return)}
                </div>
              </div>
              <div>
                <span className="text-neutral-500">Shares</span>
                <div className="text-neutral-200 font-medium">{pos.shares.toFixed(4)}</div>
              </div>
              <div>
                <span className="text-neutral-500">Cost Basis</span>
                <div className="text-neutral-200 font-medium">{formatCurrency(pos.cost_basis)}</div>
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
