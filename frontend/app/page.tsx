"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { DataStatusBar } from "@/components/layout/DataStatusBar";
import { PortfolioTab } from "@/components/dashboard/PortfolioTab";
import { OpportunitiesTab } from "@/components/dashboard/OpportunitiesTab";
import { TradeTab } from "@/components/dashboard/TradeTab";
import { PerformanceTab } from "@/components/dashboard/PerformanceTab";
import { HistoryTab } from "@/components/dashboard/HistoryTab";
import { SectorsTab } from "@/components/dashboard/SectorsTab";
import type { TabId } from "@/lib/types";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("portfolio");

  return (
    <div className="flex h-screen overflow-hidden bg-neutral-950">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
      <div className="flex-1 flex flex-col overflow-hidden">
        <DataStatusBar />
        <main className="flex-1 overflow-hidden">
          {activeTab === "portfolio" && <PortfolioTab />}
          {activeTab === "opportunities" && <OpportunitiesTab />}
          {activeTab === "trade" && <TradeTab />}
          {activeTab === "performance" && <PerformanceTab />}
          {activeTab === "sectors" && <SectorsTab />}
          {activeTab === "history" && <HistoryTab />}
        </main>
      </div>
    </div>
  );
}
