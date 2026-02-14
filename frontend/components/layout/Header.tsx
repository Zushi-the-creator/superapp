"use client";

import { RefreshCw } from "lucide-react";
import { LivePulse } from "@/components/shared/LivePulse";

interface HeaderProps {
  title: string;
  lastUpdated: Date | null;
  loading: boolean;
  onRefresh: () => void;
}

export function Header({ title, lastUpdated, loading, onRefresh }: HeaderProps) {
  const timeAgo = lastUpdated
    ? `${Math.round((Date.now() - lastUpdated.getTime()) / 1000)}s ago`
    : "...";

  return (
    <header className="flex items-center justify-between px-4 md:px-6 py-3 border-b border-neutral-800">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-100">{title}</h1>
        <div className="flex items-center gap-1.5 text-xs text-neutral-500">
          <LivePulse positive={!loading} />
          <span>{loading ? "Updating..." : `Updated ${timeAgo}`}</span>
        </div>
      </div>
      <button
        onClick={onRefresh}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        Refresh
      </button>
    </header>
  );
}
