'use client';

import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Activity, BarChart3 } from 'lucide-react';

interface Stock {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change: number;
  change_pct: number;
  signal: string;
  signal_strength: number;
  rsi: number;
  ema_fast: number;
  ema_slow: number;
  volume_ratio: number;
  sentiment_score: number;
  sentiment_label: string;
  combined_score: number;
}

interface MainChartProps {
  stock: Stock;
}

export default function MainChart({ stock }: MainChartProps) {
  const [historicalData, setHistoricalData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // In a real app, fetch historical data from backend
    // For now, we'll show the technical indicators
    setLoading(false);
  }, [stock.ticker]);

  const getSignalColor = (signal: string) => {
    switch (signal) {
      case 'BUY':
        return 'text-signal-buy';
      case 'SELL':
        return 'text-signal-sell';
      default:
        return 'text-signal-hold';
    }
  };

  const getSignalIcon = (signal: string) => {
    switch (signal) {
      case 'BUY':
        return <TrendingUp className="w-6 h-6" />;
      case 'SELL':
        return <TrendingDown className="w-6 h-6" />;
      default:
        return <Activity className="w-6 h-6" />;
    }
  };

  const getRSIStatus = (rsi: number) => {
    if (rsi < 30) return { label: 'Oversold', color: 'text-signal-buy' };
    if (rsi > 70) return { label: 'Overbought', color: 'text-signal-sell' };
    return { label: 'Neutral', color: 'text-neutral-400' };
  };

  const rsiStatus = getRSIStatus(stock.rsi);

  return (
    <div className="bg-neutral-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-neutral-700">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-bold">{stock.ticker}</h2>
              <span className="px-2 py-1 bg-neutral-700 rounded text-xs text-neutral-400">
                {stock.sector}
              </span>
            </div>
            <p className="text-sm text-neutral-400 mt-1">{stock.name}</p>
          </div>

          <div className="text-right">
            <div className="text-3xl font-bold">${stock.price.toFixed(2)}</div>
            <div
              className={`text-lg font-semibold ${
                stock.change_pct >= 0 ? 'text-signal-buy' : 'text-signal-sell'
              }`}
            >
              {stock.change >= 0 ? '+' : ''}
              {stock.change.toFixed(2)} ({stock.change_pct >= 0 ? '+' : ''}
              {stock.change_pct.toFixed(2)}%)
            </div>
          </div>
        </div>
      </div>

      {/* Signal Overview */}
      <div className="px-6 py-6">
        <div className="flex items-center justify-between p-4 bg-gradient-to-br from-neutral-700/50 to-neutral-800/50 rounded-lg border border-neutral-600">
          <div className="flex items-center gap-4">
            <div
              className={`p-3 rounded-full ${
                stock.signal === 'BUY'
                  ? 'bg-signal-buy/20 signal-buy-glow'
                  : stock.signal === 'SELL'
                  ? 'bg-signal-sell/20 signal-sell-glow'
                  : 'bg-neutral-600/20'
              }`}
            >
              <span className={getSignalColor(stock.signal)}>{getSignalIcon(stock.signal)}</span>
            </div>

            <div>
              <div className="text-sm text-neutral-400">Primary Signal</div>
              <div className={`text-2xl font-bold ${getSignalColor(stock.signal)}`}>
                {stock.signal}
              </div>
            </div>
          </div>

          <div className="text-right">
            <div className="text-sm text-neutral-400">Signal Strength</div>
            <div className="flex items-center gap-2 mt-1">
              <div className="w-32 h-2 bg-neutral-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    stock.signal === 'BUY'
                      ? 'bg-signal-buy'
                      : stock.signal === 'SELL'
                      ? 'bg-signal-sell'
                      : 'bg-neutral-500'
                  }`}
                  style={{ width: `${stock.signal_strength}%` }}
                />
              </div>
              <span className="text-lg font-bold">{stock.signal_strength}%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Technical Indicators */}
      <div className="px-6 pb-6">
        <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
          <BarChart3 className="w-4 h-4" />
          Technical Indicators
        </h3>

        <div className="grid grid-cols-3 gap-4">
          {/* RSI */}
          <div className="p-4 bg-neutral-700/50 rounded-lg border border-neutral-600">
            <div className="text-xs text-neutral-400 mb-1">RSI (14)</div>
            <div className="text-2xl font-bold">{stock.rsi.toFixed(1)}</div>
            <div className={`text-xs font-medium mt-1 ${rsiStatus.color}`}>{rsiStatus.label}</div>
            <div className="mt-2 h-1.5 bg-neutral-800 rounded-full overflow-hidden">
              <div
                className={`h-full ${
                  stock.rsi < 30
                    ? 'bg-signal-buy'
                    : stock.rsi > 70
                    ? 'bg-signal-sell'
                    : 'bg-primary-500'
                }`}
                style={{ width: `${(stock.rsi / 100) * 100}%` }}
              />
            </div>
          </div>

          {/* EMA */}
          <div className="p-4 bg-neutral-700/50 rounded-lg border border-neutral-600">
            <div className="text-xs text-neutral-400 mb-1">EMA</div>
            <div className="text-sm font-semibold">
              Fast: ${stock.ema_fast.toFixed(2)}
            </div>
            <div className="text-sm font-semibold">
              Slow: ${stock.ema_slow.toFixed(2)}
            </div>
            <div className={`text-xs font-medium mt-1 ${
              stock.ema_fast > stock.ema_slow ? 'text-signal-buy' : 'text-signal-sell'
            }`}>
              {stock.ema_fast > stock.ema_slow ? '↑ Bullish' : '↓ Bearish'}
            </div>
          </div>

          {/* Volume */}
          <div className="p-4 bg-neutral-700/50 rounded-lg border border-neutral-600">
            <div className="text-xs text-neutral-400 mb-1">Volume Ratio</div>
            <div className="text-2xl font-bold">{stock.volume_ratio.toFixed(1)}x</div>
            <div className={`text-xs font-medium mt-1 ${
              stock.volume_ratio > 2 ? 'text-yellow-500' :
              stock.volume_ratio > 1.5 ? 'text-primary-400' :
              'text-neutral-400'
            }`}>
              {stock.volume_ratio > 2 ? 'Very High' :
               stock.volume_ratio > 1.5 ? 'Above Average' :
               'Normal'}
            </div>
          </div>
        </div>
      </div>

      {/* Sentiment */}
      <div className="px-6 pb-6">
        <h3 className="text-sm font-semibold text-neutral-300 mb-3">
          News Sentiment
        </h3>

        <div className="p-4 bg-neutral-700/50 rounded-lg border border-neutral-600">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-neutral-400">Overall Sentiment</div>
              <div className={`text-xl font-bold ${
                stock.sentiment_label === 'POSITIVE' ? 'text-signal-buy' :
                stock.sentiment_label === 'NEGATIVE' ? 'text-signal-sell' :
                'text-neutral-400'
              }`}>
                {stock.sentiment_label}
              </div>
            </div>

            <div className="text-right">
              <div className="text-sm text-neutral-400">Sentiment Score</div>
              <div className="text-xl font-bold">
                {stock.sentiment_score >= 0 ? '+' : ''}
                {stock.sentiment_score.toFixed(3)}
              </div>
            </div>
          </div>

          <div className="mt-3 h-2 bg-neutral-800 rounded-full overflow-hidden">
            <div
              className={`h-full ${
                stock.sentiment_score > 0 ? 'bg-signal-buy' :
                stock.sentiment_score < 0 ? 'bg-signal-sell' :
                'bg-neutral-500'
              }`}
              style={{
                width: `${Math.abs(stock.sentiment_score) * 50 + 50}%`,
                marginLeft: stock.sentiment_score < 0 ? `${50 - Math.abs(stock.sentiment_score) * 50}%` : '50%'
              }}
            />
          </div>
        </div>
      </div>

      {/* Combined Score */}
      <div className="px-6 pb-6">
        <div className="p-4 bg-gradient-to-br from-primary-900/20 to-primary-800/10 rounded-lg border border-primary-700/30">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-neutral-400">Combined Score</div>
              <div className="text-xs text-neutral-500 mt-0.5">
                Technical (60%) + Sentiment (40%)
              </div>
            </div>
            <div className="text-3xl font-bold text-primary-400">
              {stock.combined_score}/100
            </div>
          </div>
          <div className="mt-3 h-3 bg-neutral-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary-600 to-primary-400 rounded-full"
              style={{ width: `${stock.combined_score}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
