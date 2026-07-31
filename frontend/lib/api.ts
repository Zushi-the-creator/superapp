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
  SimState,
  SimDecision,
  SimHistoryResponse,
  SimConfig,
  SimCandidatesResponse,
  Mix9State,
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

  // ── Simulator ($100k autonomous multi-strategy paper book) ──
  // MIX9 engine
  getMix9State: () => fetchJson<Mix9State>("/api/v2/mix9/state"),
  runMix9: () => fetchJson<Mix9State>("/api/v2/mix9/run", { method: "POST" }),

  getSimState: () => fetchJson<SimState>("/api/v2/sim/state"),
  getSimDecisions: (limit = 150, kinds = "") =>
    fetchJson<{ decisions: SimDecision[] }>(
      `/api/v2/sim/decisions?limit=${limit}${kinds ? `&kinds=${kinds}` : ""}`
    ),
  getSimHistory: (limit = 200) =>
    fetchJson<SimHistoryResponse>(`/api/v2/sim/history?limit=${limit}`),
  getSimCandidates: (limit = 40) =>
    fetchJson<SimCandidatesResponse>(`/api/v2/sim/candidates?limit=${limit}`),
  runSimCycle: (force = false) =>
    fetchJson<{ cycle_id: string; actions: Record<string, unknown[]> }>(
      `/api/v2/sim/run?force=${force}`,
      { method: "POST" }
    ),
  setSimConfig: (patch: Partial<SimConfig>) =>
    fetchJson<{ config: SimConfig }>("/api/v2/sim/config", {
      method: "POST",
      body: JSON.stringify(patch),
    }),
  simBuy: (ticker: string, strategy: string, dollars = 0, note = "") =>
    fetchJson<{ ok: boolean }>("/api/v2/sim/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, strategy, dollars, note }),
    }),
  simClosePosition: (position_id: number, note = "") =>
    fetchJson<{ ok: boolean }>("/api/v2/sim/close", {
      method: "POST",
      body: JSON.stringify({ position_id, note }),
    }),
  simSwitch: (position_id: number, buy_ticker: string, strategy?: string, note = "") =>
    fetchJson<{ ok: boolean; warning?: string }>("/api/v2/sim/switch", {
      method: "POST",
      body: JSON.stringify({ position_id, buy_ticker, strategy, note }),
    }),

  testAlertEmail: () =>
    fetchJson<{ success: boolean; message: string }>("/api/v2/alerts/test", {
      method: "POST",
    }),
  sendReport: () =>
    fetchJson<{ success: boolean; message: string; positions: number; buy_signals: number; upgrades: number }>("/api/v2/alerts/send-report", {
      method: "POST",
    }),
};
