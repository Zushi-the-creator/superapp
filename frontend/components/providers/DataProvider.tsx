"use client";

import React, { createContext, useContext } from "react";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { REFRESH_INTERVALS } from "@/lib/constants";
import type {
  PortfolioResponse,
  ScanResponse,
  HistoryResponse,
  PerformanceResponse,
  HealthCheckResponse,
} from "@/lib/types";

interface PollingResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  lastUpdated: Date | null;
}

interface DataContextType {
  portfolio: PollingResult<PortfolioResponse>;
  scanner: PollingResult<ScanResponse>;
  history: PollingResult<HistoryResponse>;
  performance: PollingResult<PerformanceResponse>;
  health: PollingResult<HealthCheckResponse>;
  /** Refresh every data source — call after a trade so all tabs show new positions / cash. */
  refreshAll: () => Promise<void>;
}

const DataContext = createContext<DataContextType | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  const portfolio = usePolling<PortfolioResponse>({
    fetcher: api.getPortfolio,
    interval: REFRESH_INTERVALS.portfolio,
    extendedHoursInterval: REFRESH_INTERVALS.portfolioExtHours,
    offHoursInterval: REFRESH_INTERVALS.portfolioOffHours,
  });

  // V3.4 SSOT (2026-06-17): no consumers of useData().scanner remain after the
  // Entries-tab refactor. Polling /scan/opportunities was wasted bandwidth.
  // OpportunitiesTab fetches /scan/combined directly. Keep the state shape for
  // back-compat with any latent consumers but stub the fetcher to a no-op.
  const scanner = usePolling<ScanResponse>({
    fetcher: async () => ({ opportunities: [], holdings_scores: [] } as unknown as ScanResponse),
    interval: REFRESH_INTERVALS.scanner,
    offHoursInterval: REFRESH_INTERVALS.scannerOffHours,
  });

  const history = usePolling<HistoryResponse>({
    fetcher: api.getHistory,
    interval: REFRESH_INTERVALS.health,
    offHoursInterval: REFRESH_INTERVALS.healthOffHours,
  });

  const performance = usePolling<PerformanceResponse>({
    fetcher: api.getPerformance,
    interval: REFRESH_INTERVALS.health,
    offHoursInterval: REFRESH_INTERVALS.healthOffHours,
  });

  const health = usePolling<HealthCheckResponse>({
    fetcher: api.getHealth,
    interval: REFRESH_INTERVALS.health,
    offHoursInterval: REFRESH_INTERVALS.healthOffHours,
  });

  const refreshAll = async () => {
    await Promise.all([
      portfolio.refresh(),
      scanner.refresh(),
      history.refresh(),
      performance.refresh(),
      health.refresh(),
    ]);
  };

  return (
    <DataContext.Provider value={{ portfolio, scanner, history, performance, health, refreshAll }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within DataProvider");
  return ctx;
}
