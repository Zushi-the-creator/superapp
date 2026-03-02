"use client";

import {
  BarChart3,
  History,
  TrendingUp,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { TabId } from "@/lib/types";

const tabs: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "portfolio", label: "Portfolio", icon: BarChart3 },
  { id: "opportunities", label: "Upgrades", icon: Zap },
  { id: "performance", label: "Performance", icon: TrendingUp },
  { id: "history", label: "History", icon: History },
];

interface SidebarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  alertCount?: number;
}

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  return (
    <>
      {/* Desktop sidebar */}
      <nav className="hidden md:flex flex-col w-16 lg:w-52 border-r border-neutral-800 bg-neutral-900/50 h-screen sticky top-0">
        <div className="p-3 lg:p-4 border-b border-neutral-800">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-signal-buy/20 flex items-center justify-center">
              <BarChart3 className="h-4 w-4 text-signal-buy" />
            </div>
            <span className="hidden lg:block text-sm font-semibold text-neutral-100">
              ATLAS V2
            </span>
          </div>
        </div>
        <div className="flex-1 py-2 space-y-1 px-2">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                activeTab === id
                  ? "bg-neutral-800 text-neutral-100"
                  : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/50"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="hidden lg:block">{label}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t border-neutral-800 bg-neutral-900/95 backdrop-blur-sm">
        <div className="flex items-center justify-around py-2">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className={cn(
                "flex flex-col items-center gap-0.5 px-3 py-1 text-xs transition-colors",
                activeTab === id
                  ? "text-signal-buy"
                  : "text-neutral-500"
              )}
            >
              <Icon className="h-5 w-5" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </nav>
    </>
  );
}
