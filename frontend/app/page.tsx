"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { PortfolioTab } from "@/components/dashboard/PortfolioTab";
import { HistoryTab } from "@/components/dashboard/HistoryTab";
import type { TabId } from "@/lib/types";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("portfolio");

  return (
    <div className="flex h-screen overflow-hidden bg-neutral-950">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
      <main className="flex-1 overflow-hidden">
        {activeTab === "portfolio" && <PortfolioTab />}
        {activeTab === "history" && <HistoryTab />}
      </main>
    </div>
  );
}
