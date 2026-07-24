"use client";

import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus, RefreshCw } from "lucide-react";
import type { SectorData, SectorNews } from "@/lib/types";

function SentimentIcon({ sentiment }: { sentiment: number }) {
  if (sentiment > 0) return <TrendingUp className="h-3 w-3 text-signal-buy shrink-0" />;
  if (sentiment < 0) return <TrendingDown className="h-3 w-3 text-signal-sell shrink-0" />;
  return <Minus className="h-3 w-3 text-neutral-600 shrink-0" />;
}

const labelStyle = (label: string) =>
  label === "POSITIVE" ? "bg-signal-buy/20 text-signal-buy" :
  label === "NEGATIVE" ? "bg-signal-sell/20 text-signal-sell" :
  "bg-neutral-800 text-neutral-400";

export function SectorNewsPanel({
  news,
  newsRefreshing,
  sectors,
  selectedEtf,
}: {
  news: Record<string, SectorNews> | null;
  newsRefreshing?: boolean;
  sectors: SectorData[];
  selectedEtf: string | null;
}) {
  if (!news) {
    return (
      <div className="flex items-center gap-2 py-8 justify-center text-xs text-neutral-500">
        <RefreshCw className={cn("h-3.5 w-3.5", newsRefreshing && "animate-spin")} />
        {newsRefreshing ? "Fetching sector news…" : "No sector news yet"}
      </div>
    );
  }

  // Selected sector first; otherwise leadership order (sectors is already ranked)
  const ordered = sectors
    .filter((s) => news[s.etf])
    .sort((a, b) =>
      a.etf === selectedEtf ? -1 : b.etf === selectedEtf ? 1 : a.rank - b.rank
    );
  const visible = selectedEtf ? ordered.filter((s) => s.etf === selectedEtf) : ordered;

  return (
    <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
      {visible.map((s) => {
        const n = news[s.etf];
        return (
          <div key={s.etf} className="rounded-md border border-neutral-800/70 p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-neutral-200">{s.name}</span>
                <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", labelStyle(n.label))}>
                  {n.label}
                </span>
              </div>
              <span className="text-[10px] text-neutral-600">
                +{n.pos_count} / −{n.neg_count}
              </span>
            </div>
            <ul className="space-y-1.5">
              {n.headlines.map((h, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[11px] leading-snug text-neutral-400">
                  <span className="mt-0.5"><SentimentIcon sentiment={h.sentiment} /></span>
                  <span>{h.title}</span>
                </li>
              ))}
              {n.headlines.length === 0 && (
                <li className="text-[11px] text-neutral-600">No recent headlines</li>
              )}
            </ul>
            <div className="mt-2 text-[9px] text-neutral-700">
              Updated {new Date(n.updated).toLocaleString()}
            </div>
          </div>
        );
      })}
      {visible.length === 0 && (
        <div className="py-8 text-center text-xs text-neutral-500">No news for this sector yet</div>
      )}
    </div>
  );
}
