'use client';

import { TrendingUp, TrendingDown, Activity, Zap } from 'lucide-react';

interface Stock {
  ticker: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  signal: string;
  signal_strength: number;
  combined_score: number;
  volume_ratio: number;
  is_hot: boolean;
  sentiment_label: string;
}

interface TickerFeedProps {
  stocks: Stock[];
  selectedStock: Stock | null;
  onSelectStock: (stock: Stock) => void;
}

export default function TickerFeed({ stocks, selectedStock, onSelectStock }: TickerFeedProps) {
  const getSignalColor = (signal: string) => {
    switch (signal) {
      case 'BUY':
        return 'text-signal-buy border-signal-buy/30';
      case 'SELL':
        return 'text-signal-sell border-signal-sell/30';
      default:
        return 'text-signal-hold border-neutral-600';
    }
  };

  const getSignalBg = (signal: string) => {
    switch (signal) {
      case 'BUY':
        return 'bg-signal-buy/10 signal-buy-glow';
      case 'SELL':
        return 'bg-signal-sell/10 signal-sell-glow';
      default:
        return 'bg-neutral-800/50';
    }
  };

  return (
    <div className="bg-neutral-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-neutral-700">
        <h3 className="font-semibold text-sm text-neutral-300">Live Scanner Feed</h3>
        <p className="text-xs text-neutral-500 mt-0.5">{stocks.length} stocks • Updated 15s</p>
      </div>

      {/* Stock List */}
      <div className="custom-scrollbar overflow-y-auto" style={{ maxHeight: 'calc(100vh - 250px)' }}>
        {stocks.length === 0 ? (
          <div className="p-8 text-center">
            <Activity className="w-12 h-12 text-neutral-600 mx-auto mb-3 animate-pulse" />
            <p className="text-sm text-neutral-500">Scanning stocks...</p>
            <p className="text-xs text-neutral-600 mt-1">First scan may take 30-60 seconds</p>
          </div>
        ) : (
          <div className="divide-y divide-neutral-700">
            {stocks.map((stock) => (
              <button
                key={stock.ticker}
                onClick={() => onSelectStock(stock)}
                className={`
                  w-full text-left px-4 py-3 transition-all duration-200
                  hover:bg-neutral-700/50
                  ${selectedStock?.ticker === stock.ticker ? 'bg-primary-900/20 border-l-2 border-primary-500' : ''}
                `}
              >
                <div className="flex items-start justify-between gap-2">
                  {/* Left: Ticker & Name */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm">{stock.ticker}</span>
                      {stock.is_hot && (
                        <Zap className="w-3 h-3 text-yellow-500" title="High Volume" />
                      )}
                    </div>
                    <p className="text-xs text-neutral-500 truncate">{stock.name}</p>
                  </div>

                  {/* Right: Price & Change */}
                  <div className="text-right">
                    <div className="font-semibold text-sm">${stock.price.toFixed(2)}</div>
                    <div
                      className={`text-xs font-medium ${
                        stock.change_pct >= 0 ? 'text-signal-buy' : 'text-signal-sell'
                      }`}
                    >
                      {stock.change_pct >= 0 ? '+' : ''}
                      {stock.change_pct.toFixed(2)}%
                    </div>
                  </div>
                </div>

                {/* Signal Badge */}
                <div className="flex items-center gap-2 mt-2">
                  <div
                    className={`
                      inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium
                      border ${getSignalColor(stock.signal)} ${getSignalBg(stock.signal)}
                    `}
                  >
                    {stock.signal === 'BUY' && <TrendingUp className="w-3 h-3" />}
                    {stock.signal === 'SELL' && <TrendingDown className="w-3 h-3" />}
                    {stock.signal}
                  </div>

                  {/* Combined Score */}
                  <div className="flex-1">
                    <div className="flex items-center gap-1">
                      <div className="flex-1 h-1.5 bg-neutral-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            stock.signal === 'BUY' ? 'bg-signal-buy' :
                            stock.signal === 'SELL' ? 'bg-signal-sell' :
                            'bg-neutral-500'
                          }`}
                          style={{ width: `${stock.combined_score}%` }}
                        />
                      </div>
                      <span className="text-xs text-neutral-500 font-medium w-8 text-right">
                        {stock.combined_score}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Sentiment */}
                {stock.sentiment_label !== 'NEUTRAL' && (
                  <div className="mt-1.5 text-xs text-neutral-400">
                    Sentiment:{' '}
                    <span
                      className={
                        stock.sentiment_label === 'POSITIVE'
                          ? 'text-signal-buy'
                          : 'text-signal-sell'
                      }
                    >
                      {stock.sentiment_label}
                    </span>
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
