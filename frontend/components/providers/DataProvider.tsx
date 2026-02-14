"use client";

import React, { createContext, useContext } from "react";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { REFRESH_INTERVALS } from "@/lib/constants";
import type {
  PortfolioResponse,
  ScanResponse,
  HistoryResponse,
} from "@/lib/types";

interface DataContextType {
  portfolio: {
    data: PortfolioResponse | null;
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    lastUpdated: Date | null;
  };
  scanner: {
    data: ScanResponse | null;
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    lastUpdated: Date | null;
  };
  history: {
    data: HistoryResponse | null;
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    lastUpdated: Date | null;
  };
}

const DataContext = createContext<DataContextType | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  const portfolio = usePolling<PortfolioResponse>({
    fetcher: api.getPortfolio,
    interval: REFRESH_INTERVALS.portfolio,
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

  return (
    <DataContext.Provider value={{ portfolio, scanner, history }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within DataProvider");
  return ctx;
}
