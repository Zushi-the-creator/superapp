"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { formatCurrency, formatPercent, cn, pnlColor } from "@/lib/utils";
import { LivePulse } from "@/components/shared/LivePulse";
import { SignalBadge, RegimeBadge, HealthBadge, TierBadge } from "@/components/shared/Badges";
import { Sparkline } from "@/components/shared/Sparkline";
import { StockChart } from "@/components/shared/StockChart";
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
  const [chartTicker, setChartTicker] = useState<{ ticker: string; entry: number } | null>(null);

  if (loading) return <TableSkeleton rows={4} />;

  return (
    <>
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
                onChartOpen={() => setChartTicker({ ticker: pos.ticker, entry: pos.entry_price })}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Full chart modal */}
      {chartTicker && (
        <StockChart
          ticker={chartTicker.ticker}
          entryPrice={chartTicker.entry}
          onClose={() => setChartTicker(null)}
        />
      )}
    </>
  );
}

function PositionRow({
  pos,
  isExpanded,
  onToggle,
  onChartOpen,
}: {
  pos: PositionDetail;
  isExpanded: boolean;
  onToggle: () => void;
  onChartOpen: () => void;
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
          <button
            onClick={(e) => {
              e.stopPropagation();
              onChartOpen();
            }}
            className="group relative inline-flex items-center rounded-lg px-1.5 py-1 hover:bg-neutral-800 transition-colors"
            title={`Open ${pos.ticker} chart`}
          >
            <Sparkline data={pos.sparkline} />
            <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-neutral-800/80 rounded-lg">
              <svg className="h-4 w-4 text-neutral-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
              </svg>
            </span>
          </button>
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
                <div className="flex items-center gap-1.5"><RegimeBadge regime={pos.regime} /><TierBadge tier={pos.tier} /></div>
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
              {/* Chart button on mobile (sparkline column hidden) */}
              <div className="col-span-2 md:col-span-4 lg:hidden">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onChartOpen();
                  }}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 transition-colors text-neutral-300 text-xs w-full justify-center"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
                  </svg>
                  Open Full Chart
                </button>
              </div>
              {/* Stop Loss & Targets */}
              <div className="col-span-2 md:col-span-4 mt-1 pt-2 border-t border-neutral-800/50">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <span className="text-neutral-500">Stop Loss ({pos.stop_pct}%)</span>
                    <div className={cn("font-medium", pos.current_price <= pos.stop_loss ? "text-signal-sell animate-pulse" : "text-signal-sell/60")}>
                      {formatCurrency(pos.stop_loss)}
                    </div>
                  </div>
                  <div>
                    <span className="text-neutral-500">Target 1 (+{pos.target_1_pct}%)</span>
                    <div className={cn("font-medium", pos.current_price >= pos.target_1 ? "text-signal-buy animate-pulse" : "text-signal-buy/60")}>
                      {formatCurrency(pos.target_1)}
                    </div>
                  </div>
                  <div>
                    <span className="text-neutral-500">Target 2 (+{pos.target_2_pct}%)</span>
                    <div className={cn("font-medium", pos.current_price >= pos.target_2 ? "text-signal-buy animate-pulse" : "text-signal-buy/60")}>
                      {formatCurrency(pos.target_2)}
                    </div>
                  </div>
                </div>
                {/* Visual price bar */}
                <div className="mt-2 relative h-2 bg-neutral-800 rounded-full overflow-hidden">
                  {(() => {
                    const range = pos.target_2 - pos.stop_loss;
                    const pricePct = Math.max(0, Math.min(100, ((pos.current_price - pos.stop_loss) / range) * 100));
                    const t1Pct = ((pos.target_1 - pos.stop_loss) / range) * 100;
                    return (
                      <>
                        <div className="absolute left-0 top-0 h-full bg-signal-sell/30 rounded-l-full" style={{width: `${t1Pct * 0.2}%`}} />
                        <div className={cn("absolute top-0 h-full rounded-full transition-all", pos.pnl >= 0 ? "bg-signal-buy" : "bg-signal-sell")} style={{width: `${pricePct}%`}} />
                        <div className="absolute top-0 h-full w-px bg-neutral-500" style={{left: `${t1Pct}%`}} title="Target 1" />
                      </>
                    );
                  })()}
                </div>
                <div className="flex justify-between text-[10px] text-neutral-600 mt-0.5">
                  <span>Stop</span>
                  <span>Current</span>
                  <span>Target</span>
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
