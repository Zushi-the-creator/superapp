'use client';

import { useState, useEffect } from 'react';
import TickerFeed from '@/components/TickerFeed';
import MainChart from '@/components/MainChart';
import ReasoningCard from '@/components/ReasoningCard';
import AnalystChat from '@/components/AnalystChat';
import { Activity, TrendingUp, Zap } from 'lucide-react';

interface Stock {
  ticker: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  signal: string;
  signal_strength: number;
  rsi: number;
  volume_ratio: number;
  sentiment_score: number;
  sentiment_label: string;
  combined_score: number;
  reasons: string[];
  is_hot: boolean;
}

interface ScannerStats {
  total_tickers: number;
  scanned_tickers: number;
  hot_tickers: number;
  last_full_scan: string | null;
  last_hot_scan: string | null;
}

export default function Home() {
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [topBuys, setTopBuys] = useState<Stock[]>([]);
  const [topSells, setTopSells] = useState<Stock[]>([]);
  const [volatile, setVolatile] = useState<Stock[]>([]);
  const [volumeLeaders, setVolumeLeaders] = useState<Stock[]>([]);
  const [stats, setStats] = useState<ScannerStats | null>(null);
  const [activeView, setActiveView] = useState<'buy' | 'sell' | 'volatile' | 'volume'>('buy');
  const [wsConnected, setWsConnected] = useState(false);

  // WebSocket connection for real-time updates
  useEffect(() => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const WS_URL = API_URL.replace('http', 'ws');

    let ws: WebSocket | null = null;
    let reconnectTimeout: NodeJS.Timeout;

    const connect = () => {
      try {
        ws = new WebSocket(`${WS_URL}/ws`);

        ws.onopen = () => {
          console.log('WebSocket connected');
          setWsConnected(true);

          // Send ping every 30s to keep alive
          const pingInterval = setInterval(() => {
            if (ws?.readyState === WebSocket.OPEN) {
              ws.send('ping');
            }
          }, 30000);

          return () => clearInterval(pingInterval);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            if (data.type === 'scanner_update') {
              setStats(data.stats);
              setTopBuys(data.top_buys || []);
              setTopSells(data.top_sells || []);
              setVolatile(data.most_volatile || []);
              setVolumeLeaders(data.volume_leaders || []);

              // Auto-select first stock if none selected
              if (!selectedStock && data.top_buys?.[0]) {
                setSelectedStock(data.top_buys[0]);
              }
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
        };

        ws.onclose = () => {
          console.log('WebSocket disconnected');
          setWsConnected(false);

          // Reconnect after 5 seconds
          reconnectTimeout = setTimeout(connect, 5000);
        };
      } catch (error) {
        console.error('Error creating WebSocket:', error);
        reconnectTimeout = setTimeout(connect, 5000);
      }
    };

    connect();

    // Cleanup
    return () => {
      if (ws) {
        ws.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, [selectedStock]);

  // Get active stocks based on view
  const getActiveStocks = () => {
    switch (activeView) {
      case 'buy':
        return topBuys;
      case 'sell':
        return topSells;
      case 'volatile':
        return volatile;
      case 'volume':
        return volumeLeaders;
      default:
        return topBuys;
    }
  };

  return (
    <div className="min-h-screen bg-neutral-900 text-neutral-50">
      {/* Header */}
      <header className="border-b border-neutral-800 bg-neutral-900/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-full px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-primary-700 rounded-lg flex items-center justify-center">
                <Activity className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">NASDAQ Super App</h1>
                <p className="text-sm text-neutral-400">15s Real-Time Scanner • AI Analyst</p>
              </div>
            </div>

            {/* Stats */}
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-signal-buy' : 'bg-neutral-500'} animate-pulse`} />
                <span className="text-sm text-neutral-400">
                  {wsConnected ? 'Live' : 'Connecting...'}
                </span>
              </div>

              {stats && (
                <>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-primary-400">{stats.scanned_tickers}</div>
                    <div className="text-xs text-neutral-500">Stocks Scanned</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-signal-buy">{stats.hot_tickers}</div>
                    <div className="text-xs text-neutral-500">High Volume</div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main 3-Column Layout */}
      <div className="grid grid-cols-12 gap-6 p-6 max-w-full">
        {/* Left Column: Ticker Feed */}
        <div className="col-span-3 space-y-4">
          {/* View Selector */}
          <div className="bg-neutral-800 rounded-lg p-2 grid grid-cols-2 gap-2">
            <button
              onClick={() => setActiveView('buy')}
              className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                activeView === 'buy'
                  ? 'bg-signal-buy text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <TrendingUp className="w-4 h-4 inline mr-1" />
              Buy Signals
            </button>
            <button
              onClick={() => setActiveView('sell')}
              className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                activeView === 'sell'
                  ? 'bg-signal-sell text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <TrendingUp className="w-4 h-4 inline mr-1 rotate-180" />
              Sell Signals
            </button>
            <button
              onClick={() => setActiveView('volatile')}
              className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                activeView === 'volatile'
                  ? 'bg-primary-600 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <Activity className="w-4 h-4 inline mr-1" />
              Volatile
            </button>
            <button
              onClick={() => setActiveView('volume')}
              className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                activeView === 'volume'
                  ? 'bg-primary-600 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <Zap className="w-4 h-4 inline mr-1" />
              Volume
            </button>
          </div>

          <TickerFeed
            stocks={getActiveStocks()}
            selectedStock={selectedStock}
            onSelectStock={setSelectedStock}
          />
        </div>

        {/* Center Column: Chart & Reasoning */}
        <div className="col-span-6 space-y-4">
          {selectedStock ? (
            <>
              <MainChart stock={selectedStock} />
              <ReasoningCard stock={selectedStock} />
            </>
          ) : (
            <div className="bg-neutral-800 rounded-lg p-12 text-center">
              <Activity className="w-16 h-16 text-neutral-600 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-neutral-400">
                Select a stock to view details
              </h3>
              <p className="text-sm text-neutral-500 mt-2">
                Click any stock from the left panel to see analysis
              </p>
            </div>
          )}
        </div>

        {/* Right Column: AI Analyst Chat */}
        <div className="col-span-3">
          <AnalystChat selectedStock={selectedStock} />
        </div>
      </div>
    </div>
  );
}
