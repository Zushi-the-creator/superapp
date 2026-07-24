"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, BarChart3, Compass, Grid3x3, Newspaper, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { SectorsResponse } from "@/lib/types";
import { CardSkeleton, TableSkeleton } from "@/components/shared/Skeleton";
import { RRGQuadrantChart } from "./sectors/RRGQuadrantChart";
import { SectorLeaderboard } from "./sectors/SectorLeaderboard";
import { CorrelationHeatmap } from "./sectors/CorrelationHeatmap";
import { SectorNewsPanel } from "./sectors/SectorNewsPanel";
import { PortfolioImpactPanel } from "./sectors/PortfolioImpactPanel";

export function SectorsTab() {
  const [data, setData] = useState<SectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEtf, setSelectedEtf] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.getSectors());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sector data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex flex-col gap-6 p-4 lg:p-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <CardSkeleton />
          <CardSkeleton />
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }

  // Hard failure with nothing to show — error card + retry
  if (error && !data) {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-lg border border-signal-sell/30 bg-signal-sell/5 p-6 text-center">
          <AlertCircle className="mx-auto h-8 w-8 text-signal-sell mb-3" />
          <div className="text-sm font-semibold text-neutral-200 mb-1">Couldn&apos;t load sector data</div>
          <div className="text-xs text-neutral-500 mb-4">{error}</div>
          <button
            onClick={() => { setLoading(true); load(); }}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-800 px-4 py-2 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-neutral-500">No sector data</div>;

  const { sectors, portfolio_exposure, portfolio_impact, correlation, news } = data;
  const heldSectorNames = new Set(portfolio_exposure.map((e) => e.sector));

  return (
    <div className="flex flex-col gap-6 p-4 lg:p-6">
      {/* Stale-data banner: we have data but the latest refresh failed */}
      {error && (
        <div className="flex items-center justify-between rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          <span className="flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" />
            Refresh failed — showing last loaded data
          </span>
          <button onClick={load} className="flex items-center gap-1 font-medium hover:text-amber-200">
            <RefreshCw className="h-3 w-3" /> Retry
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-neutral-100">Sector Rotation</h2>
          <p className="text-xs text-neutral-500">
            11 GICS sectors vs {data.rrg?.benchmark ?? "SPY"} · as of {data.rrg?.as_of ?? "—"}
            {selectedEtf && (
              <>
                {" · "}
                <button onClick={() => setSelectedEtf(null)} className="text-blue-400 hover:underline">
                  clear {selectedEtf} filter
                </button>
              </>
            )}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 rounded-md border border-neutral-800 px-3 py-1.5 text-xs text-neutral-400 hover:bg-neutral-800/50"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </div>

      {/* RRG quadrant + leaderboard */}
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 p-4">
          <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
            <Compass className="h-4 w-4" />
            Relative Rotation vs SPY
          </h3>
          <RRGQuadrantChart sectors={sectors} selectedEtf={selectedEtf} onSelect={setSelectedEtf} />
          <p className="mt-2 text-[10px] text-neutral-600">
            Trail = last 8 weeks. Sectors rotate clockwise: Improving → Leading → Weakening → Lagging.
          </p>
        </div>
        <div className="rounded-lg border border-neutral-800 p-4">
          <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Leadership Ranking
          </h3>
          <SectorLeaderboard
            sectors={sectors}
            heldSectorNames={heldSectorNames}
            selectedEtf={selectedEtf}
            onSelect={setSelectedEtf}
          />
        </div>
      </div>

      {/* Portfolio impact */}
      <PortfolioImpactPanel impact={portfolio_impact} exposure={portfolio_exposure} />

      {/* Correlations + news */}
      <div className="grid gap-6 xl:grid-cols-2">
        {correlation && (
          <div className="rounded-lg border border-neutral-800 p-4">
            <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
              <Grid3x3 className="h-4 w-4" />
              Sector Connections
            </h3>
            <CorrelationHeatmap correlation={correlation} selectedEtf={selectedEtf} />
          </div>
        )}
        <div className="rounded-lg border border-neutral-800 p-4">
          <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
            <Newspaper className="h-4 w-4" />
            What&apos;s Fueling the Rotation
          </h3>
          <SectorNewsPanel
            news={news}
            newsRefreshing={data.news_refreshing}
            sectors={sectors}
            selectedEtf={selectedEtf}
          />
        </div>
      </div>
    </div>
  );
}
