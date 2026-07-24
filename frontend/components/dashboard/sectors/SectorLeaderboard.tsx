"use client";

import { cn } from "@/lib/utils";
import type { SectorData } from "@/lib/types";
import { QuadrantBadge } from "./quadrant";

const pnlColor = (v: number) =>
  v > 0 ? "text-signal-buy" : v < 0 ? "text-signal-sell" : "text-neutral-400";

export function SectorLeaderboard({
  sectors,
  heldSectorNames,
  selectedEtf,
  onSelect,
}: {
  sectors: SectorData[];
  heldSectorNames: Set<string>;
  selectedEtf: string | null;
  onSelect: (etf: string | null) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-neutral-500 border-b border-neutral-800">
            <th className="text-left py-2 px-2">#</th>
            <th className="text-left px-2">Sector</th>
            <th className="text-center px-2">Rotation</th>
            <th className="text-right px-2">Lead</th>
            <th className="text-right px-2">5d</th>
            <th className="text-right px-2">20d</th>
            <th className="text-right px-2">YTD</th>
            <th className="text-center px-2">Trend</th>
            <th className="text-right px-2">MR WR</th>
          </tr>
        </thead>
        <tbody>
          {sectors.map((s) => (
            <tr
              key={s.etf}
              onClick={() => onSelect(selectedEtf === s.etf ? null : s.etf)}
              className={cn(
                "border-b border-neutral-800/50 hover:bg-neutral-800/30 cursor-pointer",
                heldSectorNames.has(s.name) && "bg-blue-500/5",
                selectedEtf === s.etf && "bg-neutral-800/50"
              )}
            >
              <td className="py-2.5 px-2 text-neutral-500 font-medium">{s.rank}</td>
              <td className="px-2">
                <div className="font-medium text-neutral-200">{s.name}</div>
                <div className="text-neutral-600">{s.etf}</div>
              </td>
              <td className="text-center px-2"><QuadrantBadge quadrant={s.quadrant} /></td>
              <td className={cn("text-right px-2 font-bold", pnlColor(s.leadership_score))}>
                {s.leadership_score > 0 ? "+" : ""}{s.leadership_score.toFixed(1)}
              </td>
              <td className={cn("text-right px-2", pnlColor(s.ret_5d))}>{s.ret_5d > 0 ? "+" : ""}{s.ret_5d.toFixed(1)}%</td>
              <td className={cn("text-right px-2", pnlColor(s.ret_20d))}>{s.ret_20d > 0 ? "+" : ""}{s.ret_20d.toFixed(1)}%</td>
              <td className={cn("text-right px-2 font-medium", pnlColor(s.ret_ytd))}>{s.ret_ytd > 0 ? "+" : ""}{s.ret_ytd.toFixed(1)}%</td>
              <td className="text-center px-2">
                <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded",
                  s.trend === "BULL" ? "bg-signal-buy/20 text-signal-buy" :
                  s.trend === "BEAR" ? "bg-signal-sell/20 text-signal-sell" :
                  "bg-neutral-800 text-neutral-400"
                )}>{s.trend}</span>
              </td>
              <td className={cn("text-right px-2",
                s.mr_wr >= 60 ? "text-signal-buy" : s.mr_wr >= 50 ? "text-amber-400" : "text-signal-sell")}>
                {s.mr_wr.toFixed(0)}%
                <span className="text-neutral-600 ml-1">({s.mr_trades}t)</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
