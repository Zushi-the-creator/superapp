"use client";

import { useState } from "react";
import { Search, Loader2, X } from "lucide-react";
import { api } from "@/lib/api";
import { formatCurrency, formatPercent, cn, pnlColor, signalBg } from "@/lib/utils";
import { SignalBadge, RegimeBadge, TierBadge } from "@/components/shared/Badges";
import { Sparkline } from "@/components/shared/Sparkline";
import type { StockAnalysis } from "@/lib/types";

export function StockSearch() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<StockAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    const ticker = query.trim().toUpperCase();
    if (!ticker) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await api.analyzeStock(ticker);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stock not found");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const clear = () => {
    setQuery("");
    setResult(null);
    setError(null);
  };

  return (
    <div className="space-y-4">
      {/* Search input */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            placeholder="Enter ticker (e.g. AAPL)"
            className="w-full pl-9 pr-8 py-2 bg-neutral-900 border border-neutral-700 rounded-lg text-sm text-neutral-100 placeholder:text-neutral-500 focus:outline-none focus:border-signal-buy/50"
            maxLength={10}
          />
          {query && (
            <button onClick={clear} className="absolute right-2 top-1/2 -translate-y-1/2">
              <X className="h-4 w-4 text-neutral-500 hover:text-neutral-300" />
            </button>
          )}
        </div>
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="px-4 py-2 bg-signal-buy/20 text-signal-buy rounded-lg text-sm font-medium hover:bg-signal-buy/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Analyze"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-lg bg-signal-sell/10 border border-signal-sell/20 text-signal-sell text-sm">
          {error}
        </div>
      )}

      {/* Result card */}
      {result && <AnalysisCard data={result} />}
    </div>
  );
}

function AnalysisCard({ data }: { data: StockAnalysis }) {
  const hasIssues = data.issues.length > 0;

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-neutral-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-neutral-100">{data.ticker}</span>
          <span className="text-lg text-neutral-200">{formatCurrency(data.live_price)}</span>
          <span className={cn("text-sm", pnlColor(data.day_change_pct))}>
            {formatPercent(data.day_change_pct)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TierBadge tier={data.tier} />
          <RegimeBadge regime={data.regime} />
          <SignalBadge signal={data.signal} />
        </div>
      </div>

      {/* Sparkline */}
      {data.sparkline.length > 0 && (
        <div className="px-4 py-2 border-b border-neutral-800/50 flex items-center gap-2">
          <span className="text-xs text-neutral-500">20d</span>
          <Sparkline data={data.sparkline} width={200} height={32} />
        </div>
      )}

      {/* Grid */}
      <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
        {/* Technical */}
        <Stat label="RSI(2)" value={data.rsi2.toFixed(1)} color={data.rsi2 < 20 ? "text-signal-buy" : data.rsi2 > 80 ? "text-signal-sell" : "text-neutral-200"} />
        <Stat label="SMA50" value={`${formatCurrency(data.sma50)} (${data.above_sma50 ? "ABOVE" : "BELOW"})`} color={data.above_sma50 ? "text-signal-buy" : "text-signal-sell"} />
        <Stat label="Win Rate" value={`${data.win_rate.toFixed(1)}% (${data.total_trades}t)`} color={data.win_rate >= 70 ? "text-signal-buy" : data.win_rate >= 55 ? "text-neutral-200" : "text-signal-sell"} />
        <Stat label="Avg Return" value={formatPercent(data.avg_return)} color={pnlColor(data.avg_return)} />

        {/* Exit zone */}
        <Stat label="Exit Zone Return" value={`${formatPercent(data.exit_zone_return)} (${data.exit_zone_wr.toFixed(0)}% WR)`} color={pnlColor(data.exit_zone_return)} sub={`${data.exit_zone_trades} trades at RSI ${data.rsi_zone}`} />
        <Stat label="Score" value={data.score.toFixed(2)} color={data.score >= 5 ? "text-signal-buy" : data.score >= 3 ? "text-neutral-200" : "text-signal-sell"} />

        {/* Sentiment */}
        <Stat label="Sentiment" value={data.sentiment_label} color={data.sentiment_label === "POSITIVE" ? "text-signal-buy" : data.sentiment_label === "NEGATIVE" ? "text-signal-sell" : "text-neutral-400"} sub={`Score: ${data.sentiment_score.toFixed(2)}`} />

        {/* Analyst */}
        <Stat label="Analyst" value={`${data.analyst_consensus} → ${formatCurrency(data.analyst_target)}`} color={data.analyst_upside > 0 ? "text-signal-buy" : "text-signal-sell"} sub={`${data.analyst_upside > 0 ? "+" : ""}${data.analyst_upside.toFixed(1)}% upside`} />
      </div>

      {/* Exit strategy */}
      <div className="px-4 pb-4 grid grid-cols-3 gap-3">
        <div className="p-2 rounded-lg bg-signal-sell/10 border border-signal-sell/20 text-center">
          <div className="text-[10px] text-neutral-500">Stop Loss (-8%)</div>
          <div className="text-sm font-medium text-signal-sell">{formatCurrency(data.stop_loss)}</div>
        </div>
        <div className="p-2 rounded-lg bg-signal-buy/10 border border-signal-buy/20 text-center">
          <div className="text-[10px] text-neutral-500">Target 1 (+10%)</div>
          <div className="text-sm font-medium text-signal-buy">{formatCurrency(data.target_1)}</div>
        </div>
        <div className="p-2 rounded-lg bg-signal-buy/10 border border-signal-buy/20 text-center">
          <div className="text-[10px] text-neutral-500">Target 2 (+20%)</div>
          <div className="text-sm font-medium text-signal-buy">{formatCurrency(data.target_2)}</div>
        </div>
      </div>

      {/* Earnings */}
      {data.earnings_date && (
        <div className="px-4 pb-3">
          <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs text-center">
            Earnings on {data.earnings_date} — WAIT before buying
          </div>
        </div>
      )}

      {/* Issues */}
      {hasIssues && (
        <div className="px-4 pb-4">
          <div className="text-xs text-neutral-500 mb-1">Issues</div>
          <div className="space-y-1">
            {data.issues.map((issue, i) => (
              <div key={i} className="text-xs text-signal-sell">{issue}</div>
            ))}
          </div>
        </div>
      )}

      {/* Headlines */}
      {data.headlines.length > 0 && (
        <div className="px-4 pb-4 border-t border-neutral-800/50 pt-3">
          <div className="text-xs text-neutral-500 mb-1">Recent News</div>
          <div className="space-y-1">
            {data.headlines.map((h, i) => (
              <div key={i} className="text-xs text-neutral-400 truncate">{h}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color, sub }: { label: string; value: string; color: string; sub?: string }) {
  return (
    <div>
      <div className="text-neutral-500">{label}</div>
      <div className={cn("font-medium", color)}>{value}</div>
      {sub && <div className="text-neutral-600 text-[10px]">{sub}</div>}
    </div>
  );
}
