'use client';

import { Lightbulb, TrendingUp, MessageSquare, BarChart2 } from 'lucide-react';

interface Stock {
  ticker: string;
  signal: string;
  signal_strength: number;
  reasons: string[];
  rsi: number;
  sentiment_label: string;
  sentiment_score: number;
  sector: string;
  combined_score: number;
}

interface ReasoningCardProps {
  stock: Stock;
}

export default function ReasoningCard({ stock }: ReasoningCardProps) {
  const getSignalColor = (signal: string) => {
    switch (signal) {
      case 'BUY':
        return 'bg-signal-buy/10 border-signal-buy/30 text-signal-buy';
      case 'SELL':
        return 'bg-signal-sell/10 border-signal-sell/30 text-signal-sell';
      default:
        return 'bg-neutral-700/50 border-neutral-600 text-neutral-400';
    }
  };

  const getActionableInsight = () => {
    if (stock.signal === 'BUY' && stock.signal_strength > 60) {
      return {
        title: 'Strong Buy Opportunity',
        message: `${stock.ticker} shows compelling buy signals with ${stock.signal_strength}% confidence based on technical and sentiment analysis.`,
        type: 'buy'
      };
    } else if (stock.signal === 'SELL' && stock.signal_strength > 60) {
      return {
        title: 'Consider Exit Position',
        message: `${stock.ticker} shows strong sell signals with ${stock.signal_strength}% confidence. Consider taking profits or exiting position.`,
        type: 'sell'
      };
    } else if (stock.signal === 'BUY' && stock.signal_strength > 40) {
      return {
        title: 'Moderate Buy Signal',
        message: `${stock.ticker} shows moderate buy signals. Consider waiting for stronger confirmation or scale in gradually.`,
        type: 'buy'
      };
    } else if (stock.signal === 'SELL' && stock.signal_strength > 40) {
      return {
        title: 'Caution Advised',
        message: `${stock.ticker} shows moderate sell signals. Monitor closely and consider risk management strategies.`,
        type: 'sell'
      };
    } else {
      return {
        title: 'Hold Position',
        message: `${stock.ticker} shows mixed signals. Current strength at ${stock.signal_strength}%. Wait for clearer indication.`,
        type: 'hold'
      };
    }
  };

  const insight = getActionableInsight();

  return (
    <div className="bg-neutral-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-neutral-700 bg-gradient-to-r from-primary-900/20 to-neutral-800">
        <div className="flex items-center gap-2">
          <Lightbulb className="w-5 h-5 text-primary-400" />
          <h3 className="text-lg font-semibold">Why {stock.signal}?</h3>
        </div>
        <p className="text-sm text-neutral-400 mt-1">
          AI-powered reasoning based on technical + sentiment analysis
        </p>
      </div>

      <div className="p-6 space-y-6">
        {/* Actionable Insight */}
        <div
          className={`p-4 rounded-lg border ${
            insight.type === 'buy'
              ? 'bg-signal-buy/10 border-signal-buy/30'
              : insight.type === 'sell'
              ? 'bg-signal-sell/10 border-signal-sell/30'
              : 'bg-neutral-700/50 border-neutral-600'
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`p-2 rounded-full ${
                insight.type === 'buy'
                  ? 'bg-signal-buy/20'
                  : insight.type === 'sell'
                  ? 'bg-signal-sell/20'
                  : 'bg-neutral-600/20'
              }`}
            >
              <TrendingUp
                className={`w-5 h-5 ${
                  insight.type === 'buy'
                    ? 'text-signal-buy'
                    : insight.type === 'sell'
                    ? 'text-signal-sell rotate-180'
                    : 'text-neutral-400'
                }`}
              />
            </div>
            <div className="flex-1">
              <h4 className="font-semibold text-sm">{insight.title}</h4>
              <p className="text-sm text-neutral-300 mt-1">{insight.message}</p>
            </div>
          </div>
        </div>

        {/* Three-Point Reasoning */}
        <div className="space-y-4">
          <h4 className="text-sm font-semibold text-neutral-300">
            3-Point Analysis Framework
          </h4>

          {/* 1. Technical Logic */}
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-900/30 border border-primary-700/50 flex items-center justify-center">
              <BarChart2 className="w-4 h-4 text-primary-400" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h5 className="font-semibold text-sm">1. Technical Logic</h5>
              </div>
              <ul className="mt-2 space-y-1">
                {stock.reasons.map((reason, idx) => (
                  <li key={idx} className="text-sm text-neutral-300 flex items-start gap-2">
                    <span className="text-primary-400 mt-0.5">•</span>
                    <span>{reason}</span>
                  </li>
                ))}
                {stock.reasons.length === 0 && (
                  <li className="text-sm text-neutral-500">No significant technical signals</li>
                )}
              </ul>
            </div>
          </div>

          {/* 2. Sentiment Score */}
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-900/30 border border-primary-700/50 flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-primary-400" />
            </div>
            <div className="flex-1">
              <h5 className="font-semibold text-sm">2. Sentiment Analysis</h5>
              <div className="mt-2 space-y-1">
                <p className="text-sm text-neutral-300">
                  News sentiment is{' '}
                  <span
                    className={`font-semibold ${
                      stock.sentiment_label === 'POSITIVE'
                        ? 'text-signal-buy'
                        : stock.sentiment_label === 'NEGATIVE'
                        ? 'text-signal-sell'
                        : 'text-neutral-400'
                    }`}
                  >
                    {stock.sentiment_label}
                  </span>{' '}
                  with a score of{' '}
                  <span className="font-semibold">
                    {stock.sentiment_score >= 0 ? '+' : ''}
                    {stock.sentiment_score.toFixed(3)}
                  </span>
                </p>
                {stock.sentiment_label === 'POSITIVE' && (
                  <p className="text-sm text-neutral-400">
                    Positive news flow supports bullish thesis
                  </p>
                )}
                {stock.sentiment_label === 'NEGATIVE' && (
                  <p className="text-sm text-neutral-400">
                    Negative news flow suggests caution
                  </p>
                )}
                {stock.sentiment_label === 'NEUTRAL' && (
                  <p className="text-sm text-neutral-400">
                    Neutral news flow - focus on technicals
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* 3. Sector Correlation */}
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-900/30 border border-primary-700/50 flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-primary-400" />
            </div>
            <div className="flex-1">
              <h5 className="font-semibold text-sm">3. Sector Context</h5>
              <div className="mt-2">
                <p className="text-sm text-neutral-300">
                  {stock.ticker} operates in the{' '}
                  <span className="font-semibold text-primary-400">{stock.sector}</span> sector
                </p>
                <p className="text-sm text-neutral-400 mt-1">
                  Combined technical + sentiment score:{' '}
                  <span className="font-semibold text-primary-400">
                    {stock.combined_score}/100
                  </span>
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Risk Disclaimer */}
        <div className="pt-4 border-t border-neutral-700">
          <p className="text-xs text-neutral-500">
            ⚠️ This analysis is for informational purposes only and not financial advice. Always
            conduct your own research and consider your risk tolerance before trading.
          </p>
        </div>
      </div>
    </div>
  );
}
