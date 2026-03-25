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
}

const DataContext = createContext<DataContextType | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  const portfolio = usePolling<PortfolioResponse>({
    fetcher: api.getPortfolio,
    interval: REFRESH_INTERVALS.portfolio,
    extendedHoursInterval: REFRESH_INTERVALS.portfolioExtHours,
    offHoursInterval: REFRESH_INTERVALS.portfolioOffHours,
  });

  const scanner = usePolling<ScanResponse>({
    fetcher: api.getOpportunities,
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

  return (
    <DataContext.Provider value={{ portfolio, scanner, history, performance, health }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within DataProvider");
  return ctx;
}
