"use client";

import { cn } from "@/lib/utils";
import { AlertTriangle, Shield } from "lucide-react";
import type { PortfolioImpact, PortfolioSectorExposure, RRGQuadrant } from "@/lib/types";
import { QUADRANT_COLORS, QuadrantBadge } from "./quadrant";

const QUADRANT_ORDER: { key: keyof PortfolioImpact["quadrant_weights"]; label: string; quadrant: RRGQuadrant }[] = [
  { key: "leading", label: "Leading", quadrant: "Leading" },
  { key: "improving", label: "Improving", quadrant: "Improving" },
  { key: "weakening", label: "Weakening", quadrant: "Weakening" },
  { key: "lagging", label: "Lagging", quadrant: "Lagging" },
  { key: "unknown", label: "Unknown", quadrant: "Unknown" },
];

export function PortfolioImpactPanel({
  impact,
  exposure,
}: {
  impact: PortfolioImpact;
  exposure: PortfolioSectorExposure[];
}) {
  const hhiStyle =
    impact.concentration_label === "HIGH" ? "bg-signal-sell/20 text-signal-sell" :
    impact.concentration_label === "MODERATE" ? "bg-amber-500/20 text-amber-400" :
    "bg-signal-buy/20 text-signal-buy";

  return (
    <div className="rounded-lg border border-neutral-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-neutral-300 flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Portfolio vs Sector Rotation
        </h3>
        <div className="flex items-center gap-2 text-[10px]">
          <span className={cn("font-bold px-1.5 py-0.5 rounded", hhiStyle)}>
            CONCENTRATION {impact.concentration_label} (HHI {impact.concentration_hhi})
          </span>
          <span className={cn("font-bold px-1.5 py-0.5 rounded",
            impact.leadership_score > 0 ? "bg-signal-buy/20 text-signal-buy" : "bg-signal-sell/20 text-signal-sell")}>
            LEADERSHIP {impact.leadership_score > 0 ? "+" : ""}{impact.leadership_score.toFixed(1)}
          </span>
        </div>
      </div>

      {/* Stacked quadrant-weight bar */}
      <div className="mb-1 flex h-5 w-full overflow-hidden rounded-full bg-neutral-800">
        {QUADRANT_ORDER.map(({ key, quadrant }) => {
          const w = impact.quadrant_weights[key];
          if (!w) return null;
          return (
            <div
              key={key}
              title={`${quadrant}: ${w.toFixed(0)}%`}
              className="h-full flex items-center justify-center text-[9px] font-bold text-neutral-950"
              style={{ width: `${w}%`, backgroundColor: QUADRANT_COLORS[quadrant] }}
            >
              {w >= 8 ? `${w.toFixed(0)}%` : ""}
            </div>
          );
        })}
      </div>
      <div className="mb-4 flex gap-3 text-[9px] text-neutral-500">
        {QUADRANT_ORDER.filter(({ key }) => impact.quadrant_weights[key] > 0).map(({ key, label, quadrant }) => (
          <span key={key} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: QUADRANT_COLORS[quadrant] }} />
            {label}
          </span>
        ))}
      </div>

      {/* Flags */}
      {impact.flags.length > 0 && (
        <div className="mb-4 space-y-1.5">
          {impact.flags.map((flag, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-300">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              {flag}
            </div>
          ))}
        </div>
      )}

      {/* Per-sector exposure bars, colored by rotation quadrant */}
      <div className="space-y-2">
        {exposure.map((exp) => (
          <div key={exp.sector} className="flex items-center gap-3">
            <div className="w-28 text-xs text-neutral-400 truncate">{exp.sector}</div>
            <div className="flex-1 h-4 bg-neutral-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(exp.weight, 100)}%`,
                  backgroundColor: QUADRANT_COLORS[exp.quadrant] ?? QUADRANT_COLORS.Unknown,
                }}
              />
            </div>
            <div className="w-12 text-right text-xs font-medium text-neutral-300">{exp.weight.toFixed(0)}%</div>
            <div className="w-20 text-center"><QuadrantBadge quadrant={exp.quadrant} /></div>
            <div className="w-32 text-[10px] text-neutral-600 truncate">{exp.tickers.join(", ")}</div>
          </div>
        ))}
      </div>

      {impact.avg_held_sector_correlation !== null && (
        <div className="mt-3 text-[10px] text-neutral-500">
          Avg correlation between held sectors:{" "}
          <span className={impact.avg_held_sector_correlation >= 0.7 ? "text-amber-400 font-semibold" : "text-neutral-400"}>
            {impact.avg_held_sector_correlation.toFixed(2)}
          </span>
          {impact.avg_held_sector_correlation < 0.4 && " — well diversified across sectors"}
        </div>
      )}
    </div>
  );
}
