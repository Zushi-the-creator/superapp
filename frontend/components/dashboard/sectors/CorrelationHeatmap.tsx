"use client";

import { cn } from "@/lib/utils";
import type { SectorCorrelation } from "@/lib/types";

// Diverging scale: negative = blue, positive = red, near-zero = transparent
function cellColor(corr: number, isDiagonal: boolean): string {
  if (isDiagonal) return "rgba(115,115,115,0.25)";
  const alpha = Math.min(Math.abs(corr), 1) * 0.75;
  return corr >= 0 ? `rgba(239,68,68,${alpha})` : `rgba(59,130,246,${alpha})`;
}

export function CorrelationHeatmap({
  correlation,
  selectedEtf,
}: {
  correlation: SectorCorrelation;
  selectedEtf: string | null;
}) {
  const { etfs, matrix, window_days, high_pairs } = correlation;

  return (
    <div>
      <div className="overflow-x-auto">
        <div
          className="grid gap-px min-w-[420px]"
          style={{ gridTemplateColumns: `48px repeat(${etfs.length}, minmax(28px, 1fr))` }}
        >
          <div />
          {etfs.map((etf) => (
            <div key={etf} className={cn(
              "text-center text-[9px] font-medium py-1",
              selectedEtf === etf ? "text-neutral-100" : "text-neutral-500"
            )}>
              {etf}
            </div>
          ))}
          {etfs.map((rowEtf, i) => (
            <div key={rowEtf} className="contents">
              <div className={cn(
                "text-right pr-2 text-[9px] font-medium flex items-center justify-end",
                selectedEtf === rowEtf ? "text-neutral-100" : "text-neutral-500"
              )}>
                {rowEtf}
              </div>
              {etfs.map((colEtf, j) => {
                const highlighted = selectedEtf !== null && (rowEtf === selectedEtf || colEtf === selectedEtf);
                const dimOthers = selectedEtf !== null && !highlighted;
                return (
                  <div
                    key={colEtf}
                    title={`${rowEtf} × ${colEtf}: ${matrix[i][j].toFixed(2)}`}
                    className={cn(
                      "aspect-square flex items-center justify-center text-[8px] rounded-sm",
                      dimOthers ? "opacity-30" : "opacity-100",
                      Math.abs(matrix[i][j]) > 0.45 || i === j ? "text-neutral-100" : "text-neutral-400"
                    )}
                    style={{ backgroundColor: cellColor(matrix[i][j], i === j) }}
                  >
                    {i === j ? "" : matrix[i][j].toFixed(1).replace("0.", ".")}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-[10px] text-neutral-500">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: "rgba(59,130,246,0.6)" }} />
          <span>inverse</span>
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-neutral-800" />
          <span>uncorrelated</span>
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: "rgba(239,68,68,0.6)" }} />
          <span>moves together</span>
        </div>
        <span>{window_days}d daily returns</span>
      </div>

      {high_pairs.length > 0 && (
        <div className="mt-2 text-[10px] text-neutral-500">
          Tightest pairs:{" "}
          {high_pairs.slice(0, 3).map((p, i) => (
            <span key={`${p.a}-${p.b}`} className="text-neutral-400">
              {i > 0 && " · "}{p.a}×{p.b} <span className="text-amber-400">{p.corr.toFixed(2)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
