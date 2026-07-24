import { API_URL } from "./constants";
import type {
  PortfolioResponse,
  HealthCheckResponse,
  ScanResponse,
  HistoryResponse,
  TradeResult,
  StockAnalysis,
  ChartData,
  PerformanceResponse,
  CombinedResponse,
  SectorsResponse,
  DataStatus,
} from "./types";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      signal: controller.signal,
      ...options,
    });
    if (!res.ok) {
      throw new Error(`API error: ${res.status} ${res.statusText}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  // Portfolio
  getPortfolio: () => fetchJson<PortfolioResponse>("/api/v2/portfolio"),

  // Health
  getHealth: () => fetchJson<HealthCheckResponse>("/api/v2/portfolio/health"),

  // Scanner — return data even if scan is in progress (empty results are fine)
  getOpportunities: () => fetchJson<ScanResponse>("/api/v2/scan/opportunities"),
  refreshScan: () =>
    fetchJson<ScanResponse>("/api/v2/scan/refresh", { method: "POST" }),
  // Full refresh: clears today's cache and re-runs evaluator + Phase 3 validation.
  // OpportunitiesTab's "Full Scan" button calls this. Endpoint: /api/v2/scan/refresh-all
  refreshAll: () =>
    fetchJson<{ status: string; refreshed?: number; failed?: number; entries?: number }>(
      "/api/v2/scan/refresh-all",
      { method: "POST" }
    ),

  // Trade
  buy: (ticker: string, shares: number, price: number, notes = "") =>
    fetchJson<TradeResult>("/api/v2/positions/buy", {
      method: "POST",
      body: JSON.stringify({ ticker, shares, price, notes }),
    }),
  sell: (ticker: string, shares: number, price: number, notes = "") =>
    fetchJson<TradeResult>("/api/v2/positions/sell", {
      method: "POST",
      body: JSON.stringify({ ticker, shares, price, notes }),
    }),
  deposit: (amount: number, date?: string, notes = "") =>
    fetchJson<{ success: boolean; message: string; total_deposited?: number }>(
      "/api/v2/positions/deposit",
      {
        method: "POST",
        body: JSON.stringify({ amount, date, notes }),
      }
    ),

  // Analyze
  analyzeStock: (ticker: string) =>
    fetchJson<StockAnalysis>(`/api/v2/analyze/${ticker.toUpperCase()}`),

  // Chart
  getChartData: (ticker: string, days = 90) =>
    fetchJson<ChartData>(`/api/v2/chart/${ticker.toUpperCase()}?days=${days}`),

  // Performance
  getPerformance: () => fetchJson<PerformanceResponse>("/api/v2/performance"),

  // History
  getHistory: (ticker?: string) =>
    fetchJson<HistoryResponse>(
      `/api/v2/positions/history${ticker ? `?ticker=${ticker}` : ""}`
    ),

  // Alerts
  getAlertConfig: () =>
    fetchJson<Record<string, unknown>>("/api/v2/alerts/config"),
  updateAlertConfig: (config: Record<string, unknown>) =>
    fetchJson<{ success: boolean; message: string }>("/api/v2/alerts/config", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  // Sectors
  getSectors: () => fetchJson<SectorsResponse>("/api/v2/sectors"),

  // Combined (MR + Momentum unified)
  getCombined: () => fetchJson<CombinedResponse>("/api/v2/scan/combined"),

  // Data status (cache freshness, market session, regime)
  getDataStatus: () => fetchJson<DataStatus>("/api/v2/data/status"),

  testAlertEmail: () =>
    fetchJson<{ success: boolean; message: string }>("/api/v2/alerts/test", {
      method: "POST",
    }),
  sendReport: () =>
    fetchJson<{ success: boolean; message: string; positions: number; buy_signals: number; upgrades: number }>("/api/v2/alerts/send-report", {
      method: "POST",
    }),
};
