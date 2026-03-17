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
  MomentumResponse,
  CombinedResponse,
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
  refreshHealth: () =>
    fetchJson<HealthCheckResponse>("/api/v2/portfolio/health/refresh", {
      method: "POST",
    }),

  // Scanner — return data even if scan is in progress (empty results are fine)
  getOpportunities: () => fetchJson<ScanResponse>("/api/v2/scan/opportunities"),
  refreshScan: () =>
    fetchJson<ScanResponse>("/api/v2/scan/refresh", { method: "POST" }),

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
  // Momentum
  getMomentum: () => fetchJson<MomentumResponse>("/api/v2/momentum/opportunities"),
  refreshMomentum: () =>
    fetchJson<MomentumResponse>("/api/v2/momentum/refresh", { method: "POST" }),

  // Combined (MR + Momentum unified)
  getCombined: () => fetchJson<CombinedResponse>("/api/v2/scan/combined"),
  refreshAll: () =>
    fetchJson<{ status: string; message: string }>("/api/v2/scan/refresh-all", { method: "POST" }),

  testAlertEmail: () =>
    fetchJson<{ success: boolean; message: string }>("/api/v2/alerts/test", {
      method: "POST",
    }),
  sendReport: () =>
    fetchJson<{ success: boolean; message: string; positions: number; buy_signals: number; upgrades: number }>("/api/v2/alerts/send-report", {
      method: "POST",
    }),
};
