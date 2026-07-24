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
    HEALTHY: "bg-signal-buy/15 text-signal-buy border-signal-buy/30",
    DIP_BUY: "bg-signal-buy/15 text-signal-buy border-signal-buy/30",
    SIDEWAYS: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    WEAK: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    PULLBACK: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    CORRECTION: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    BEAR: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
    BEAR_BOUNCE: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
    BELOW_SMA200: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
    DANGER: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
    CRISIS: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
    FEAR: "bg-signal-sell/15 text-signal-sell border-signal-sell/30",
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

export function TierBadge({ tier }: { tier: string }) {
  if (!tier || tier === "NONE") return null;

  const colors: Record<string, string> = {
    EXTREME:
      "bg-purple-500/20 text-purple-300 border-purple-500/40 ring-1 ring-purple-500/30",
    STRONG:
      "bg-blue-500/20 text-blue-300 border-blue-500/40",
    STANDARD:
      "bg-neutral-700/40 text-neutral-400 border-neutral-600/30",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider border",
        colors[tier] || colors.STANDARD
      )}
    >
      {tier}
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
