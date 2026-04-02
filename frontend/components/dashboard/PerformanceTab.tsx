"use client";

import { useState, useRef, useCallback, useMemo } from "react";
import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { formatCurrency, formatDateFull, cn, pnlColor } from "@/lib/utils";
import type { DailyPnL } from "@/lib/types";

// Strategy milestones for chart annotations
const MILESTONES: { date: string; label: string; color: string }[] = [
  { date: "2026-01-07", label: "First Trades", color: "#737373" },
  { date: "2026-01-20", label: "Rotation #1", color: "#737373" },
  { date: "2026-02-04", label: "ATLAS V2.1", color: "#3b82f6" },
  { date: "2026-02-06", label: "Golden Era Start", color: "#22c55e" },
  { date: "2026-02-12", label: "Earnings Veto", color: "#f59e0b" },
  { date: "2026-02-24", label: "V2.4 Deploy", color: "#06b6d4" },
  { date: "2026-02-28", label: "Iran War Crash", color: "#ef4444" },
  { date: "2026-03-14", label: "V2.6 + Regime Gate", color: "#a855f7" },
  { date: "2026-04-01", label: "10yr Backtest + Tiingo", color: "#3b82f6" },
];

function linearRegression(points: { x: number; y: number }[]) {
  const n = points.length;
  if (n < 2) return { slope: 0, intercept: 0 };
  let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
  for (const p of points) {
    sumX += p.x;
    sumY += p.y;
    sumXY += p.x * p.y;
    sumXX += p.x * p.x;
  }
  const denom = n * sumXX - sumX * sumX;
  if (denom === 0) return { slope: 0, intercept: sumY / n };
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

export function PerformanceTab() {
  const { performance } = useData();
  const { data, loading, lastUpdated, refresh } = performance;
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const trades = data?.trades ?? [];
  const dailyPnl = data?.daily_pnl ?? [];

  // Chart dimensions — taller for better readability
  const chartW = 900;
  const chartH = 300;
  const padL = 55;
  const padR = 20;
  const padT = 24;
  const padB = 36;
  const plotW = chartW - padL - padR;
  const plotH = chartH - padT - padB;

  // Memoized chart calculations — only recompute when data changes, not on hover
  const chartData = useMemo(() => {
    let chartPath = "";
    let areaPath = "";
    let zeroY = 0;
    let minPnl = 0;
    let maxPnl = 0;
    const range = () => maxPnl - minPnl || 1;
    const toX = (i: number) => padL + (i / Math.max(dailyPnl.length - 1, 1)) * plotW;
    const toY = (v: number) => padT + plotH - ((v - minPnl) / range()) * plotH;

    if (dailyPnl.length > 1) {
      minPnl = Math.min(...dailyPnl.map((d) => d.pnl_pct), 0);
      maxPnl = Math.max(...dailyPnl.map((d) => d.pnl_pct), 0);
      zeroY = toY(0);

      const points = dailyPnl.map((d, i) => `${toX(i).toFixed(1)},${toY(d.pnl_pct).toFixed(1)}`);
      chartPath = `M${points.join("L")}`;
      areaPath = `M${padL},${zeroY.toFixed(1)}L${points.join("L")}L${toX(dailyPnl.length - 1).toFixed(1)},${zeroY.toFixed(1)}Z`;
    }

    // Trend line (linear regression)
    let trendPath = "";
    if (dailyPnl.length > 3) {
      const pts = dailyPnl.map((d, i) => ({ x: i, y: d.pnl_pct }));
      const { slope, intercept } = linearRegression(pts);
      const y0 = intercept;
      const yN = slope * (dailyPnl.length - 1) + intercept;
      trendPath = `M${toX(0).toFixed(1)},${toY(y0).toFixed(1)}L${toX(dailyPnl.length - 1).toFixed(1)},${toY(yN).toFixed(1)}`;
    }

    // X-axis labels — show ~5 dates
    const xLabels: { x: number; label: string }[] = [];
    if (dailyPnl.length > 1) {
      const step = Math.max(1, Math.floor(dailyPnl.length / 5));
      for (let i = 0; i < dailyPnl.length; i += step) {
        xLabels.push({ x: toX(i), label: dailyPnl[i].date.slice(5) });
      }
      const lastIdx = dailyPnl.length - 1;
      if (xLabels[xLabels.length - 1]?.label !== dailyPnl[lastIdx].date.slice(5)) {
        xLabels.push({ x: toX(lastIdx), label: dailyPnl[lastIdx].date.slice(5) });
      }
    }

    // Y-axis grid lines
    const yGridLines: { y: number; label: string }[] = [];
    if (dailyPnl.length > 1) {
      const r = range();
      const step = r > 10 ? 5 : r > 4 ? 2 : 1;
      for (let v = Math.ceil(minPnl / step) * step; v <= maxPnl; v += step) {
        yGridLines.push({ y: toY(v), label: `${v.toFixed(0)}%` });
      }
    }

    // Milestones mapped to chart x positions
    const milestoneMarkers = dailyPnl.length > 1 ? MILESTONES.map((m) => {
      const idx = dailyPnl.findIndex((d) => d.date >= m.date);
      if (idx < 0) return null;
      return { ...m, x: toX(idx), idx };
    }).filter(Boolean) as (typeof MILESTONES[0] & { x: number; idx: number })[] : [];

    return { chartPath, areaPath, zeroY, minPnl, maxPnl, trendPath, xLabels, yGridLines, milestoneMarkers, toX, toY };
  }, [dailyPnl, padL, padR, padT, padB, plotW, plotH]);

  const { chartPath, areaPath, zeroY, trendPath, xLabels, yGridLines, milestoneMarkers } = chartData;
  const toX = chartData.toX;
  const toY = chartData.toY;

  // Hover handling
  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || dailyPnl.length < 2) return;
    const rect = svgRef.current.getBoundingClientRect();
    const svgX = ((e.clientX - rect.left) / rect.width) * chartW;
    // Find closest data point
    const idx = Math.round(((svgX - padL) / plotW) * (dailyPnl.length - 1));
    const clamped = Math.max(0, Math.min(dailyPnl.length - 1, idx));
    setHoverIdx(clamped);
  }, [dailyPnl.length, chartW, plotW, padL]);

  const handleMouseLeave = useCallback(() => setHoverIdx(null), []);

  const hoverPoint: DailyPnL | null = hoverIdx !== null ? dailyPnl[hoverIdx] : null;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Performance"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Summary cards — Row 1: Key metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {/* CAGR */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">CAGR</span>
            <div className={cn("text-xl font-bold", pnlColor(data?.cagr ?? 0))}>
              {(data?.cagr ?? 0) >= 0 ? "+" : ""}{(data?.cagr ?? 0).toFixed(1)}%
            </div>
            <span className="text-[10px] text-neutral-500">annualized</span>
          </div>
          {/* Total P&L */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Total P&L</span>
            {(() => {
              const totalPnl = (data?.total_realized ?? 0) + (data?.total_unrealized ?? 0) - (data?.total_fees ?? 0);
              const totalPct = (data?.total_deposited ?? 0) > 0
                ? (totalPnl / (data?.total_deposited ?? 1)) * 100 : 0;
              return (
                <>
                  <div className={cn("text-xl font-bold", pnlColor(totalPct))}>
                    {totalPct >= 0 ? "+" : ""}{totalPct.toFixed(1)}%
                  </div>
                  <span className={cn("text-[10px]", pnlColor(totalPnl))}>
                    {formatCurrency(totalPnl)}
                  </span>
                </>
              );
            })()}
          </div>
          {/* Max Drawdown */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Max Drawdown</span>
            <div className="text-xl font-bold text-signal-sell">
              {(data?.max_drawdown ?? 0).toFixed(1)}%
            </div>
            <span className="text-[10px] text-neutral-500">worst peak-to-trough</span>
          </div>
          {/* Sharpe Ratio */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Sharpe Ratio</span>
            <div className={cn("text-xl font-bold", (data?.sharpe_ratio ?? 0) >= 1 ? "text-signal-buy" : (data?.sharpe_ratio ?? 0) >= 0 ? "text-neutral-300" : "text-signal-sell")}>
              {(data?.sharpe_ratio ?? 0).toFixed(2)}
            </div>
            <span className="text-[10px] text-neutral-500">risk-adjusted</span>
          </div>
          {/* Profit Factor */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Profit Factor</span>
            <div className={cn("text-xl font-bold", (data?.profit_factor ?? 0) >= 1 ? "text-signal-buy" : "text-signal-sell")}>
              {(data?.profit_factor ?? 0).toFixed(2)}
            </div>
            <span className="text-[10px] text-neutral-500">wins / losses</span>
          </div>
          {/* Win Rate */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Win Rate</span>
            <div className={cn("text-xl font-bold", (data?.win_rate ?? 0) >= 50 ? "text-signal-buy" : "text-signal-sell")}>
              {data?.win_rate?.toFixed(0) ?? 0}%
            </div>
            <span className="text-[10px] text-neutral-500">
              {data?.win_count ?? 0}W / {data?.loss_count ?? 0}L ({data?.total_trades ?? 0} trades)
            </span>
          </div>
        </div>

        {/* Row 2: Breakdown */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Unrealized</span>
            <div className={cn("text-xl font-bold", pnlColor(data?.total_unrealized ?? 0))}>
              {formatCurrency(data?.total_unrealized ?? 0)}
            </div>
            <span className="text-[10px] text-neutral-500">open positions</span>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Realized</span>
            <div className={cn("text-xl font-bold", pnlColor(data?.total_realized ?? 0))}>
              {formatCurrency(data?.total_realized ?? 0)}
            </div>
            <span className="text-[10px] text-neutral-500">closed trades</span>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Fees + Tax</span>
            <div className="text-xl font-bold text-neutral-400">
              {formatCurrency(data?.total_fees ?? 0)}
            </div>
            <span className="text-[10px] text-neutral-500">on {formatCurrency(data?.total_deposited ?? 0)}</span>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Avg Win / Loss</span>
            <div className="text-lg font-bold">
              <span className="text-signal-buy">+{data?.avg_win_pct?.toFixed(1) ?? 0}%</span>
              <span className="text-neutral-600 mx-1">/</span>
              <span className="text-signal-sell">{data?.avg_loss_pct?.toFixed(1) ?? 0}%</span>
            </div>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Avg Hold</span>
            <div className="text-xl font-bold text-neutral-300">
              {(data?.avg_hold_days ?? 0).toFixed(0)}d
            </div>
            <span className="text-[10px] text-neutral-500">trading days</span>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <span className="text-xs text-neutral-500">Best / Worst</span>
            <div className="text-sm font-bold">
              <span className="text-signal-buy">{data?.best_trade ?? "–"}</span>
              <span className="text-neutral-600 mx-1">/</span>
              <span className="text-signal-sell">{data?.worst_trade ?? "–"}</span>
            </div>
          </div>
        </div>

        {/* Daily P&L Chart */}
        {dailyPnl.length > 1 && (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-neutral-300">
                Portfolio P&L %
              </h3>
              {/* Hover info badge */}
              {hoverPoint && (
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-neutral-400">{formatDateFull(hoverPoint.date)}</span>
                  <span className={cn("font-semibold", pnlColor(hoverPoint.pnl_pct))}>
                    {hoverPoint.pnl_pct >= 0 ? "+" : ""}{hoverPoint.pnl_pct.toFixed(2)}%
                  </span>
                  <span className="text-neutral-500">{formatCurrency(hoverPoint.portfolio_value)}</span>
                  <span className="text-neutral-600">{hoverPoint.positions} pos</span>
                </div>
              )}
            </div>
            <svg
              ref={svgRef}
              viewBox={`0 0 ${chartW} ${chartH}`}
              className="w-full h-auto cursor-crosshair select-none"
              preserveAspectRatio="xMidYMid meet"
              onMouseMove={handleMouseMove}
              onMouseLeave={handleMouseLeave}
            >
              {/* Y-axis grid lines */}
              {yGridLines.map((gl, i) => (
                <g key={`grid-${i}`}>
                  <line
                    x1={padL} y1={gl.y} x2={chartW - padR} y2={gl.y}
                    stroke="#262626" strokeWidth="0.5"
                  />
                  <text x={padL - 6} y={gl.y + 3.5} textAnchor="end" fill="#525252" fontSize="9">
                    {gl.label}
                  </text>
                </g>
              ))}

              {/* Zero line (stronger) */}
              <line
                x1={padL} y1={zeroY} x2={chartW - padR} y2={zeroY}
                stroke="#525252" strokeWidth="1" strokeDasharray="4,4"
              />
              <text x={padL - 6} y={zeroY + 3.5} textAnchor="end" fill="#737373" fontSize="10" fontWeight="600">
                0%
              </text>

              {/* Milestone annotations */}
              {milestoneMarkers.map((m, i) => (
                <g key={`ms-${i}`}>
                  <line
                    x1={m.x} y1={padT} x2={m.x} y2={padT + plotH}
                    stroke={m.color} strokeWidth="0.8" strokeDasharray="3,3" opacity="0.6"
                  />
                  <text
                    x={m.x}
                    y={padT - 4}
                    textAnchor="middle"
                    fill={m.color}
                    fontSize="8"
                    fontWeight="500"
                    opacity="0.8"
                  >
                    {m.label}
                  </text>
                </g>
              ))}

              {/* Area fill — gradient from green/red to transparent */}
              <defs>
                <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={dailyPnl[dailyPnl.length - 1]?.pnl_pct >= 0 ? "#22c55e" : "#ef4444"} stopOpacity="0.15" />
                  <stop offset="100%" stopColor={dailyPnl[dailyPnl.length - 1]?.pnl_pct >= 0 ? "#22c55e" : "#ef4444"} stopOpacity="0.02" />
                </linearGradient>
              </defs>
              <path d={areaPath} fill="url(#areaGrad)" />

              {/* Main P&L line */}
              <path
                d={chartPath}
                fill="none"
                stroke={dailyPnl[dailyPnl.length - 1]?.pnl_pct >= 0 ? "#22c55e" : "#ef4444"}
                strokeWidth="2"
                strokeLinejoin="round"
              />

              {/* Trend line */}
              {trendPath && (
                <path
                  d={trendPath}
                  fill="none"
                  stroke="#fbbf24"
                  strokeWidth="1.5"
                  strokeDasharray="6,4"
                  opacity="0.5"
                />
              )}

              {/* X-axis labels */}
              {xLabels.map((xl, i) => (
                <text key={i} x={xl.x} y={chartH - 6} textAnchor="middle" fill="#525252" fontSize="9">
                  {xl.label}
                </text>
              ))}

              {/* End value dot + label */}
              {dailyPnl.length > 0 && (() => {
                const last = dailyPnl[dailyPnl.length - 1];
                const cx = toX(dailyPnl.length - 1);
                const cy = toY(last.pnl_pct);
                const color = last.pnl_pct >= 0 ? "#22c55e" : "#ef4444";
                return (
                  <>
                    <circle cx={cx} cy={cy} r="4" fill={color} />
                    <text x={cx - 8} y={cy - 10} textAnchor="end" fill={color} fontSize="11" fontWeight="bold">
                      {last.pnl_pct >= 0 ? "+" : ""}{last.pnl_pct.toFixed(1)}%
                    </text>
                  </>
                );
              })()}

              {/* Hover crosshair + dot + tooltip */}
              {hoverIdx !== null && hoverPoint && (() => {
                const cx = toX(hoverIdx);
                const cy = toY(hoverPoint.pnl_pct);
                const color = hoverPoint.pnl_pct >= 0 ? "#22c55e" : "#ef4444";
                return (
                  <>
                    {/* Vertical crosshair */}
                    <line
                      x1={cx} y1={padT} x2={cx} y2={padT + plotH}
                      stroke="#525252" strokeWidth="0.5"
                    />
                    {/* Horizontal crosshair to Y axis */}
                    <line
                      x1={padL} y1={cy} x2={cx} y2={cy}
                      stroke="#525252" strokeWidth="0.5" strokeDasharray="2,2"
                    />
                    {/* Dot */}
                    <circle cx={cx} cy={cy} r="5" fill={color} stroke="#0a0a0a" strokeWidth="2" />
                    {/* Y-axis value label */}
                    <rect
                      x={0} y={cy - 8} width={padL - 4} height={16}
                      rx="3" fill="#262626"
                    />
                    <text x={padL - 8} y={cy + 4} textAnchor="end" fill={color} fontSize="9" fontWeight="600">
                      {hoverPoint.pnl_pct >= 0 ? "+" : ""}{hoverPoint.pnl_pct.toFixed(1)}%
                    </text>
                    {/* Tooltip box */}
                    {(() => {
                      const tooltipW = 145;
                      const tooltipH = 62;
                      let tx = cx + 12;
                      if (tx + tooltipW > chartW - padR) tx = cx - tooltipW - 12;
                      let ty = cy - tooltipH / 2;
                      if (ty < padT) ty = padT;
                      if (ty + tooltipH > padT + plotH) ty = padT + plotH - tooltipH;
                      return (
                        <g>
                          <rect
                            x={tx} y={ty} width={tooltipW} height={tooltipH}
                            rx="6" fill="#1a1a1a" stroke="#333" strokeWidth="0.5"
                          />
                          <text x={tx + 8} y={ty + 16} fill="#a3a3a3" fontSize="9">
                            {hoverPoint.date}
                          </text>
                          <text x={tx + 8} y={ty + 31} fill={color} fontSize="12" fontWeight="700">
                            {hoverPoint.pnl_pct >= 0 ? "+" : ""}{hoverPoint.pnl_pct.toFixed(2)}%
                          </text>
                          <text x={tx + 8} y={ty + 45} fill="#737373" fontSize="9">
                            {formatCurrency(hoverPoint.portfolio_value)} · {formatCurrency(hoverPoint.pnl)}
                          </text>
                          <text x={tx + 8} y={ty + 57} fill="#525252" fontSize="8">
                            {hoverPoint.positions} position{hoverPoint.positions !== 1 ? "s" : ""}
                          </text>
                        </g>
                      );
                    })()}
                  </>
                );
              })()}

              {/* Invisible hover rects for each data point (better hit area) */}
              {dailyPnl.map((_, i) => (
                <rect
                  key={i}
                  x={toX(i) - plotW / dailyPnl.length / 2}
                  y={padT}
                  width={plotW / dailyPnl.length}
                  height={plotH}
                  fill="transparent"
                />
              ))}
            </svg>

            {/* Legend */}
            <div className="flex flex-wrap items-center gap-4 mt-2 text-[10px] text-neutral-500">
              <span className="flex items-center gap-1">
                <span className="inline-block w-4 h-0.5 bg-signal-buy rounded" /> P&L
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-4 h-0.5 bg-amber-400 rounded opacity-50" style={{ borderBottom: "1px dashed" }} /> Trend
              </span>
              {milestoneMarkers.slice(0, 4).map((m, i) => (
                <span key={i} className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: m.color, opacity: 0.6 }} />
                  {m.label}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Trades table */}
        {trades.length > 0 && (
          <div className="rounded-xl border border-neutral-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900/50">
                  <th className="text-left px-4 py-3 text-xs text-neutral-500 font-medium">Ticker</th>
                  <th className="text-left px-3 py-3 text-xs text-neutral-500 font-medium">Result</th>
                  <th className="text-left px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Entry</th>
                  <th className="text-left px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Exit</th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">Days</th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Entry $</th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">Exit $</th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">P&L</th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">P&L %</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.ticker}-${t.entry_date}-${i}`} className="border-b border-neutral-800/50 hover:bg-neutral-800/30">
                    <td className="px-4 py-3 font-medium text-neutral-200">{t.ticker}</td>
                    <td className="px-3 py-3">
                      <span className={cn(
                        "inline-flex px-2 py-0.5 rounded text-xs font-medium",
                        t.result === "WIN" ? "bg-signal-buy/15 text-signal-buy" :
                        t.result === "LOSS" ? "bg-signal-sell/15 text-signal-sell" :
                        "bg-blue-500/15 text-blue-400"
                      )}>
                        {t.result}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-neutral-400 text-xs hidden md:table-cell">
                      {formatDateFull(t.entry_date)}
                    </td>
                    <td className="px-3 py-3 text-neutral-400 text-xs hidden md:table-cell">
                      {t.exit_date ? formatDateFull(t.exit_date) : "Open"}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-400">{t.hold_days}d</td>
                    <td className="text-right px-3 py-3 text-neutral-400 hidden md:table-cell">
                      {formatCurrency(t.entry_price)}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-400 hidden md:table-cell">
                      {formatCurrency(t.exit_price)}
                    </td>
                    <td className={cn("text-right px-3 py-3 font-medium", pnlColor(t.pnl))}>
                      {formatCurrency(t.pnl)}
                    </td>
                    <td className={cn("text-right px-3 py-3 font-medium", pnlColor(t.pnl_pct))}>
                      {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Loading state for chart */}
        {dailyPnl.length <= 1 && loading && (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <div className="h-[200px] flex items-center justify-center">
              <span className="text-sm text-neutral-500 animate-pulse">Loading chart data...</span>
            </div>
          </div>
        )}

        {trades.length === 0 && !loading && (
          <div className="rounded-xl border border-neutral-800 p-8 text-center text-neutral-500">
            No trade data yet.
          </div>
        )}
      </div>
    </div>
  );
}
