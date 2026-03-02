"use client";

import { cn } from "@/lib/utils";

interface LivePulseProps {
  positive: boolean;
  session?: string; // PRE_MARKET / REGULAR / AFTER_HOURS / CLOSED
}

const SESSION_CONFIG: Record<string, { color: string; label: string; pulse: boolean }> = {
  PRE_MARKET:   { color: "bg-blue-400",    label: "PRE",  pulse: true },
  REGULAR:      { color: "",               label: "",     pulse: true }, // uses positive prop
  AFTER_HOURS:  { color: "bg-amber-400",   label: "AH",   pulse: true },
  CLOSED:       { color: "bg-neutral-500", label: "CLOSED", pulse: false },
};

export function LivePulse({ positive, session }: LivePulseProps) {
  const cfg = SESSION_CONFIG[session || ""] || SESSION_CONFIG.CLOSED;

  // CLOSED — static gray dot
  if (!cfg.pulse) {
    return (
      <span className="flex items-center gap-1.5">
        <span className="relative flex h-2 w-2">
          <span className="relative inline-flex rounded-full h-2 w-2 bg-neutral-500" />
        </span>
        <span className="text-[10px] text-neutral-500 font-medium">{cfg.label}</span>
      </span>
    );
  }

  // REGULAR — green/red based on day change (original behavior)
  const dotColor = session === "REGULAR" || !session
    ? (positive ? "bg-signal-buy" : "bg-signal-sell")
    : cfg.color;

  return (
    <span className="flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", dotColor)} />
        <span className={cn("relative inline-flex rounded-full h-2 w-2", dotColor)} />
      </span>
      {cfg.label && (
        <span className={cn(
          "text-[10px] font-medium",
          session === "PRE_MARKET" ? "text-blue-400" :
          session === "AFTER_HOURS" ? "text-amber-400" :
          "text-neutral-400"
        )}>
          {cfg.label}
        </span>
      )}
    </span>
  );
}
