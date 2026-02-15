"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  ComposedChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { X, TrendingUp, TrendingDown, Calendar, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { formatCurrency, cn, pnlColor } from "@/lib/utils";
import type { ChartData } from "@/lib/types";

const PERIODS = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
] as const;

interface StockChartProps {
  ticker: string;
  entryPrice?: number;
  onClose: () => void;
}

export function StockChart({ ticker, entryPrice, onClose }: StockChartProps) {
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState(90);
  const [showVolume, setShowVolume] = useState(true);
  const [showSignals, setShowSignals] = useState(true);
  const backdropRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback(async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getChartData(ticker, days);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chart");
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    fetchData(period);
  }, [fetchData, period]);

  // Close on ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Close on backdrop click
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current) onClose();
  };

  const candles = data?.candles ?? [];
  const signals = data?.signals ?? [];
  const position = data?.position;
  const entry = entryPrice ?? position?.entry_price;

  // Price stats
  const lastPrice = candles.length > 0 ? candles[candles.length - 1].close : 0;
  const firstPrice = candles.length > 0 ? candles[0].close : 0;
  const periodChange = firstPrice > 0 ? ((lastPrice - firstPrice) / firstPrice) * 100 : 0;
  const periodHigh = candles.length > 0 ? Math.max(...candles.map(c => c.high)) : 0;
  const periodLow = candles.length > 0 ? Math.min(...candles.map(c => c.low)) : 0;
  const avgVolume = candles.length > 0 ? candles.reduce((s, c) => s + c.volume, 0) / candles.length : 0;

  // Merge signals into candles for rendering markers
  const signalDates = new Set(signals.filter(s => showSignals).map(s => s.date));
  const signalMap = new Map(signals.map(s => [s.date, s]));

  const chartData = candles.map(c => ({
    ...c,
    dateShort: c.date.slice(5), // MM-DD
    signal: signalDates.has(c.date) ? signalMap.get(c.date) : undefined,
    volumeColor: c.close >= c.open ? "#10b98140" : "#ef444440",
  }));

  // Buy signal count in this period
  const buySignals = signals.filter(s => s.type === "BUY").length;
  const obSignals = signals.filter(s => s.type === "OVERBOUGHT").length;

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-end md:items-center justify-center"
      onClick={handleBackdropClick}
    >
      <div className={cn(
        "bg-neutral-950 border border-neutral-800 w-full max-h-[95vh] overflow-y-auto",
        "md:max-w-5xl md:rounded-2xl md:max-h-[85vh]",
        "rounded-t-2xl" // mobile bottom sheet
      )}>
        {/* Drag indicator (mobile) */}
        <div className="flex justify-center pt-2 md:hidden">
          <div className="w-10 h-1 rounded-full bg-neutral-700" />
        </div>

        {/* Header */}
        <div className="sticky top-0 z-10 bg-neutral-950/95 backdrop-blur-sm border-b border-neutral-800/50 px-4 md:px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-lg font-bold text-neutral-100">{ticker}</span>
                  <span className="text-lg font-semibold text-neutral-100">{formatCurrency(lastPrice)}</span>
                  <span className={cn("text-sm font-medium flex items-center gap-0.5", pnlColor(periodChange))}>
                    {periodChange >= 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                    {periodChange >= 0 ? "+" : ""}{periodChange.toFixed(2)}%
                  </span>
                </div>
                {entry && entry > 0 && (
                  <div className="flex items-center gap-2 text-xs text-neutral-500">
                    <span>Entry: {formatCurrency(entry)}</span>
                    <span className={cn("font-medium", pnlColor(((lastPrice - entry) / entry) * 100))}>
                      P&L: {(((lastPrice - entry) / entry) * 100).toFixed(2)}%
                    </span>
                    {position && <span>{position.shares.toFixed(2)} shares</span>}
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-neutral-800 transition-colors text-neutral-400 hover:text-neutral-200"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Period tabs + toggles */}
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <div className="flex bg-neutral-900 rounded-lg p-0.5 border border-neutral-800">
              {PERIODS.map(p => (
                <button
                  key={p.days}
                  onClick={() => setPeriod(p.days)}
                  className={cn(
                    "px-3 py-1 text-xs font-medium rounded-md transition-all",
                    period === p.days
                      ? "bg-neutral-700 text-neutral-100 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-300"
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowVolume(!showVolume)}
              className={cn(
                "px-2.5 py-1 text-[10px] rounded-md border transition-colors",
                showVolume
                  ? "border-blue-500/40 bg-blue-500/10 text-blue-400"
                  : "border-neutral-700 text-neutral-500 hover:text-neutral-400"
              )}
            >
              VOL
            </button>
            <button
              onClick={() => setShowSignals(!showSignals)}
              className={cn(
                "px-2.5 py-1 text-[10px] rounded-md border transition-colors",
                showSignals
                  ? "border-signal-buy/40 bg-signal-buy/10 text-signal-buy"
                  : "border-neutral-700 text-neutral-500 hover:text-neutral-400"
              )}
            >
              SIGNALS
            </button>
            <div className="ml-auto flex gap-3 text-[10px] text-neutral-500">
              <span>H: {formatCurrency(periodHigh)}</span>
              <span>L: {formatCurrency(periodLow)}</span>
              <span>Vol: {avgVolume > 1_000_000 ? `${(avgVolume / 1_000_000).toFixed(1)}M` : `${(avgVolume / 1_000).toFixed(0)}K`}</span>
            </div>
          </div>
        </div>

        {/* Chart body */}
        <div className="px-2 md:px-4 py-4">
          {loading && (
            <div className="flex items-center justify-center h-80 text-neutral-500">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              Loading chart...
            </div>
          )}
          {error && (
            <div className="flex items-center justify-center h-80 text-signal-sell text-sm">
              {error}
            </div>
          )}
          {!loading && !error && chartData.length > 0 && (
            <>
              {/* Main price chart */}
              <div className="h-72 md:h-96">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={periodChange >= 0 ? "#10b981" : "#ef4444"} stopOpacity={0.2} />
                        <stop offset="100%" stopColor={periodChange >= 0 ? "#10b981" : "#ef4444"} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                    <XAxis
                      dataKey="dateShort"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#525252", fontSize: 10 }}
                      interval={Math.max(0, Math.floor(chartData.length / 8))}
                    />
                    <YAxis
                      domain={["auto", "auto"]}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#525252", fontSize: 10 }}
                      tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                      width={55}
                    />
                    <Tooltip content={<ChartTooltip entry={entry} />} />

                    {/* Price area + line */}
                    <Area
                      type="monotone"
                      dataKey="close"
                      stroke={periodChange >= 0 ? "#10b981" : "#ef4444"}
                      strokeWidth={2}
                      fill="url(#priceGradient)"
                      dot={false}
                      activeDot={{ r: 4, stroke: "#fff", strokeWidth: 1 }}
                    />

                    {/* SMA50 line */}
                    <Line
                      type="monotone"
                      dataKey="sma50"
                      stroke="#f59e0b"
                      strokeWidth={1}
                      strokeDasharray="4 2"
                      dot={false}
                      connectNulls
                    />

                    {/* Entry price line */}
                    {entry && entry > 0 && (
                      <ReferenceLine
                        y={entry}
                        stroke="#3b82f6"
                        strokeDasharray="6 3"
                        strokeWidth={1}
                        label={{
                          value: `Entry $${entry.toFixed(2)}`,
                          position: "right",
                          fill: "#3b82f6",
                          fontSize: 10,
                        }}
                      />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Volume chart */}
              {showVolume && (
                <div className="h-16 md:h-20 mt-1">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={chartData} margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
                      <XAxis dataKey="dateShort" hide />
                      <YAxis hide />
                      <Bar
                        dataKey="volume"
                        fill="#404040"
                        radius={[1, 1, 0, 0]}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Signal markers strip */}
              {showSignals && signals.length > 0 && (
                <div className="mt-4 px-2">
                  <div className="flex items-center gap-2 mb-2">
                    <Calendar className="h-3.5 w-3.5 text-neutral-500" />
                    <span className="text-[10px] text-neutral-500 uppercase tracking-wider">
                      Signal History
                    </span>
                    <span className="text-[10px] text-signal-buy">{buySignals} buys</span>
                    <span className="text-[10px] text-amber-400">{obSignals} overbought</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {signals.slice(-20).map((s, i) => (
                      <div
                        key={i}
                        className={cn(
                          "px-2 py-1 rounded-md text-[10px] font-medium border",
                          s.type === "BUY"
                            ? "bg-signal-buy/10 text-signal-buy border-signal-buy/30"
                            : "bg-amber-500/10 text-amber-400 border-amber-500/30"
                        )}
                      >
                        <span className="font-bold">{s.type === "BUY" ? "B" : "OB"}</span>
                        <span className="text-neutral-500 ml-1">{s.date.slice(5)}</span>
                        <span className="ml-1">${s.price.toFixed(0)}</span>
                        <span className="text-neutral-600 ml-0.5">R{s.rsi.toFixed(0)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Legend */}
              <div className="flex items-center gap-4 mt-4 px-2 text-[10px] text-neutral-500 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <div className={cn("w-4 h-0.5 rounded", periodChange >= 0 ? "bg-signal-buy" : "bg-signal-sell")} />
                  <span>Close</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-4 h-0.5 rounded bg-amber-500" style={{ borderTop: "1px dashed #f59e0b" }} />
                  <span>SMA50</span>
                </div>
                {entry && entry > 0 && (
                  <div className="flex items-center gap-1.5">
                    <div className="w-4 h-0.5 rounded bg-blue-500" style={{ borderTop: "1px dashed #3b82f6" }} />
                    <span>Entry</span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ChartTooltip({ active, payload, label, entry }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  const pnl = entry && entry > 0 ? ((d.close - entry) / entry) * 100 : null;

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-neutral-400 mb-1">{d.date}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <span className="text-neutral-500">O</span>
        <span className="text-neutral-200 text-right">{formatCurrency(d.open)}</span>
        <span className="text-neutral-500">H</span>
        <span className="text-neutral-200 text-right">{formatCurrency(d.high)}</span>
        <span className="text-neutral-500">L</span>
        <span className="text-neutral-200 text-right">{formatCurrency(d.low)}</span>
        <span className="text-neutral-500">C</span>
        <span className={cn("text-right font-medium", d.close >= d.open ? "text-signal-buy" : "text-signal-sell")}>
          {formatCurrency(d.close)}
        </span>
        {d.sma50 && (
          <>
            <span className="text-amber-500">SMA50</span>
            <span className="text-amber-400 text-right">{formatCurrency(d.sma50)}</span>
          </>
        )}
        {d.volume > 0 && (
          <>
            <span className="text-neutral-500">Vol</span>
            <span className="text-neutral-300 text-right">
              {d.volume > 1_000_000 ? `${(d.volume / 1_000_000).toFixed(1)}M` : `${(d.volume / 1_000).toFixed(0)}K`}
            </span>
          </>
        )}
      </div>
      {pnl !== null && (
        <div className={cn("mt-1 pt-1 border-t border-neutral-800 font-medium", pnlColor(pnl))}>
          vs Entry: {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
        </div>
      )}
      {d.signal && (
        <div className={cn(
          "mt-1 pt-1 border-t border-neutral-800 font-bold",
          d.signal.type === "BUY" ? "text-signal-buy" : "text-amber-400"
        )}>
          {d.signal.type} Signal (RSI {d.signal.rsi})
        </div>
      )}
    </div>
  );
}
