"use client";

import { useState, useEffect, useCallback, useRef } from "react";

interface UsePollingOptions<T> {
  fetcher: () => Promise<T>;
  interval: number;
  extendedHoursInterval?: number; // Polling during pre-market / after-hours
  offHoursInterval?: number; // Slower polling outside US market hours
  enabled?: boolean;
}

interface UsePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  lastUpdated: Date | null;
}

type MarketSession = "REGULAR" | "EXTENDED" | "CLOSED";

function getMarketSession(): MarketSession {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  if (day === 0 || day === 6) return "CLOSED";
  const minutes = et.getHours() * 60 + et.getMinutes();
  if (minutes >= 570 && minutes <= 960) return "REGULAR"; // 9:30 AM - 4:00 PM ET
  if ((minutes >= 240 && minutes < 570) || (minutes > 960 && minutes <= 1200)) return "EXTENDED"; // 4-9:30 AM or 4-8 PM
  return "CLOSED";
}

export function usePolling<T>({
  fetcher,
  interval,
  extendedHoursInterval,
  offHoursInterval,
  enabled = true,
}: UsePollingOptions<T>): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const errorCountRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setLoading((prev) => data === null ? true : prev); // Only show loading on first fetch
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
      errorCountRef.current = 0;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      errorCountRef.current = Math.min(errorCountRef.current + 1, 6);
    } finally {
      setLoading(false);
    }
  }, [data]);

  useEffect(() => {
    if (!enabled) return;

    refresh();

    // Use dynamic interval based on market session (3-tier)
    const getInterval = () => {
      const session = getMarketSession();
      if (session === "REGULAR") return interval;
      if (session === "EXTENDED" && extendedHoursInterval) return extendedHoursInterval;
      return offHoursInterval || interval;
    };

    // Exponential backoff on errors: 30s, 60s, 120s, 240s... capped at normal interval
    let timeoutId: ReturnType<typeof setTimeout>;
    const tick = () => {
      refresh();
      const normalInterval = getInterval();
      const errorBackoff = Math.min(30_000 * Math.pow(2, errorCountRef.current - 1), normalInterval);
      const nextInterval = errorCountRef.current > 0 ? errorBackoff : normalInterval;
      timeoutId = setTimeout(tick, nextInterval);
    };
    timeoutId = setTimeout(tick, getInterval());

    return () => clearTimeout(timeoutId);
  }, [refresh, interval, extendedHoursInterval, offHoursInterval, enabled]);

  return { data, loading, error, refresh, lastUpdated };
}
