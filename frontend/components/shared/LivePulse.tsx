"use client";

import { isUSMarketOpen } from "@/lib/utils";

export function LivePulse({ positive }: { positive: boolean }) {
  const open = isUSMarketOpen();

  if (!open) {
    return (
      <span className="flex items-center gap-1.5">
        <span className="relative flex h-2 w-2">
          <span className="relative inline-flex rounded-full h-2 w-2 bg-neutral-500" />
        </span>
        <span className="text-[10px] text-neutral-500 font-medium">CLOSED</span>
      </span>
    );
  }

  const color = positive ? "bg-signal-buy" : "bg-signal-sell";
  return (
    <span className="relative flex h-2 w-2">
      <span
        className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-75`}
      />
      <span
        className={`relative inline-flex rounded-full h-2 w-2 ${color}`}
      />
    </span>
  );
}
