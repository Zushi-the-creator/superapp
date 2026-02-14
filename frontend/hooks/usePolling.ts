"use client";

import { useState, useEffect, useCallback, useRef } from "react";

interface UsePollingOptions<T> {
  fetcher: () => Promise<T>;
  interval: number;
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

function isUSMarketOpen(): boolean {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const minutes = et.getHours() * 60 + et.getMinutes();
  return minutes >= 570 && minutes <= 960; // 9:30 AM - 4:00 PM ET
}

export function usePolling<T>({
  fetcher,
  interval,
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

    // Use dynamic interval based on market hours
    const getInterval = () => {
      if (!offHoursInterval) return interval;
      return isUSMarketOpen() ? interval : offHoursInterval;
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
  }, [refresh, interval, offHoursInterval, enabled]);

  return { data, loading, error, refresh, lastUpdated };
}
