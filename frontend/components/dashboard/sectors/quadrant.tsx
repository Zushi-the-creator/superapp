import type { RRGQuadrant } from "@/lib/types";

export const QUADRANT_COLORS: Record<RRGQuadrant, string> = {
  Leading: "#10b981",
  Improving: "#3b82f6",
  Weakening: "#f59e0b",
  Lagging: "#ef4444",
  Unknown: "#6b7280",
};

export const QUADRANT_BADGE: Record<RRGQuadrant, string> = {
  Leading: "bg-signal-buy/20 text-signal-buy",
  Improving: "bg-blue-500/20 text-blue-400",
  Weakening: "bg-amber-500/20 text-amber-400",
  Lagging: "bg-signal-sell/20 text-signal-sell",
  Unknown: "bg-neutral-800 text-neutral-400",
};

export function QuadrantBadge({ quadrant }: { quadrant: RRGQuadrant }) {
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${QUADRANT_BADGE[quadrant] ?? QUADRANT_BADGE.Unknown}`}>
      {quadrant.toUpperCase()}
    </span>
  );
}
