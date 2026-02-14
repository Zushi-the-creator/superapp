"use client";

import { cn, signalBg } from "@/lib/utils";

export function SignalBadge({ signal }: { signal: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        signalBg(signal)
      )}
    >
      {signal}
    </span>
  );
}

export function RegimeBadge({ regime }: { regime: string }) {
  const colors: Record<string, string> = {
    BULL: "bg-signal-buy/15 text-signal-buy border-signal-buy/30",
    SIDEWAYS: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    BEAR: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        colors[regime] || "bg-neutral-700/50 text-neutral-300 border-neutral-600/30"
      )}
    >
      {regime}
    </span>
  );
}

export function HealthBadge({ issues }: { issues: string[] }) {
  const hasIssues = issues.length > 0;
  const critical = issues.some(
    (i) =>
      i.includes("SELL") ||
      i.includes("CRASH") ||
      i.includes("BELOW SMA50") ||
      i.includes("BEAR")
  );

  if (!hasIssues) {
    return (
      <span className="inline-flex h-3 w-3 rounded-full bg-signal-buy ring-2 ring-signal-buy/30" />
    );
  }
  if (critical) {
    return (
      <span className="inline-flex h-3 w-3 rounded-full bg-signal-sell ring-2 ring-signal-sell/30" />
    );
  }
  return (
    <span className="inline-flex h-3 w-3 rounded-full bg-amber-500 ring-2 ring-amber-500/30" />
  );
}
