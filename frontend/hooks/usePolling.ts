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

  const lastErrorRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
      lastErrorRef.current = false;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      lastErrorRef.current = true;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    refresh();

    // Use dynamic interval based on market hours
    const getInterval = () => {
      if (!offHoursInterval) return interval;
      return isUSMarketOpen() ? interval : offHoursInterval;
    };

    // Re-evaluate interval every tick; retry faster (10s) on error
    let timeoutId: ReturnType<typeof setTimeout>;
    const tick = () => {
      refresh();
      const nextInterval = lastErrorRef.current ? 10_000 : getInterval();
      timeoutId = setTimeout(tick, nextInterval);
    };
    timeoutId = setTimeout(tick, getInterval());

    return () => clearTimeout(timeoutId);
  }, [refresh, interval, offHoursInterval, enabled]);

  return { data, loading, error, refresh, lastUpdated };
}
