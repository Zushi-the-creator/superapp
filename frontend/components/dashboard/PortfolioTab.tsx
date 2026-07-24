"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { KPICards } from "./KPICards";
import { PositionsTable } from "./PositionsTable";
import { StockSearch } from "./StockSearch";
import { AlertSettings } from "./AlertSettings";

export function PortfolioTab() {
  const { portfolio } = useData();
  const { data, loading, lastUpdated, refresh } = portfolio;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Portfolio"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        <KPICards summary={data?.summary ?? null} loading={loading && !data} marketRegime={data?.market_regime} />

        <PositionsTable
          positions={data?.positions ?? []}
          loading={loading && !data}
        />

        {/* Stock Search + Alert Settings */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <h3 className="text-sm font-semibold text-neutral-200 mb-3">Analyze Stock</h3>
            <StockSearch />
          </div>
          <div>
            <AlertSettings />
          </div>
        </div>

      </div>
    </div>
  );
}
