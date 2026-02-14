"use client";

import { ShieldCheck, AlertTriangle, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { cn, signalColor } from "@/lib/utils";
import { api } from "@/lib/api";
import { useState } from "react";

export function HealthTab() {
  const { health } = useData();
  const { data, loading, lastUpdated, refresh } = health;
  const [refreshing, setRefreshing] = useState(false);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshHealth();
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const alerts = data?.alerts ?? [];
  const criticals = alerts.filter((a) => a.severity === "CRITICAL");
  const warnings = alerts.filter((a) => a.severity === "WARNING");
  const infos = alerts.filter(
    (a) => a.severity !== "CRITICAL" && a.severity !== "WARNING"
  );

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Health Monitor"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <SummaryCard
            icon={XCircle}
            label="Critical"
            count={criticals.length}
            color="text-signal-sell"
            bg="bg-signal-sell/10"
          />
          <SummaryCard
            icon={AlertTriangle}
            label="Warnings"
            count={warnings.length}
            color="text-amber-400"
            bg="bg-amber-500/10"
          />
          <SummaryCard
            icon={CheckCircle}
            label="Passing"
            count={(data?.holdings ?? 0) - criticals.length - warnings.length}
            color="text-signal-buy"
            bg="bg-signal-buy/10"
          />
          <SummaryCard
            icon={ShieldCheck}
            label="Holdings"
            count={data?.holdings ?? 0}
            color="text-blue-400"
            bg="bg-blue-500/10"
          />
        </div>

        {/* Force refresh button */}
        <button
          onClick={handleForceRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm text-neutral-300 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          Run Full Health Check (10 rules)
        </button>

        {/* Alert list */}
        {alerts.length === 0 && !loading && (
          <div className="rounded-xl border border-signal-buy/30 bg-signal-buy/5 p-6 text-center">
            <CheckCircle className="h-8 w-8 text-signal-buy mx-auto mb-2" />
            <p className="text-signal-buy font-medium">All holdings pass health check</p>
            <p className="text-neutral-500 text-xs mt-1">
              Last checked: {data?.last_check || "never"}
            </p>
          </div>
        )}

        <div className="space-y-2">
          {criticals.map((alert, i) => (
            <AlertCard key={`c-${i}`} alert={alert} />
          ))}
          {warnings.map((alert, i) => (
            <AlertCard key={`w-${i}`} alert={alert} />
          ))}
          {infos.map((alert, i) => (
            <AlertCard key={`i-${i}`} alert={alert} />
          ))}
        </div>

        {/* Position details */}
        {data?.positions && data.positions.length > 0 && (
          <div className="rounded-xl border border-neutral-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-900/50">
              <span className="text-xs text-neutral-500 font-medium">
                Detailed Position Checks
              </span>
            </div>
            <div className="divide-y divide-neutral-800/50">
              {data.positions.map((pos: Record<string, unknown>, i: number) => (
                <div key={i} className="px-4 py-3 text-xs">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-neutral-200">
                      {String(pos.ticker)}
                    </span>
                    <span className={signalColor(String(pos.signal || ""))}>
                      {String(pos.signal)}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-neutral-400">
                    <span>RSI: {Number(pos.rsi2).toFixed(1)}</span>
                    <span>WR: {Number(pos.wr).toFixed(1)}%</span>
                    <span>SMA50: {pos.above_sma50 ? "Above" : "Below"}</span>
                  </div>
                  {(pos.issues as string[])?.length > 0 && (
                    <div className="mt-1 text-signal-sell">
                      {(pos.issues as string[]).join(" | ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  count,
  color,
  bg,
}: {
  icon: React.ElementType;
  label: string;
  count: number;
  color: string;
  bg: string;
}) {
  return (
    <div className={cn("rounded-xl border border-neutral-800 p-4", bg)}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className={cn("h-4 w-4", color)} />
        <span className="text-xs text-neutral-400">{label}</span>
      </div>
      <div className={cn("text-2xl font-bold", color)}>{count}</div>
    </div>
  );
}

function AlertCard({
  alert,
}: {
  alert: { severity: string; ticker: string; signal: string; summary: string; issues: string[] };
}) {
  const severityStyles: Record<string, string> = {
    CRITICAL: "border-signal-sell/40 bg-signal-sell/5",
    WARNING: "border-amber-500/40 bg-amber-500/5",
    OPPORTUNITY: "border-signal-buy/40 bg-signal-buy/5",
    INFO: "border-neutral-700 bg-neutral-900/50",
  };

  const severityIcons: Record<string, React.ElementType> = {
    CRITICAL: XCircle,
    WARNING: AlertTriangle,
    OPPORTUNITY: CheckCircle,
    INFO: ShieldCheck,
  };

  const Icon = severityIcons[alert.severity] || ShieldCheck;

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        severityStyles[alert.severity] || severityStyles.INFO
      )}
    >
      <div className="flex items-start gap-3">
        <Icon
          className={cn(
            "h-5 w-5 mt-0.5 shrink-0",
            signalColor(alert.severity)
          )}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-neutral-100">
              {alert.ticker}
            </span>
            <span
              className={cn(
                "text-xs font-medium",
                signalColor(alert.signal)
              )}
            >
              {alert.signal}
            </span>
          </div>
          <div className="text-xs text-neutral-400 space-y-0.5">
            {alert.issues.map((issue, i) => (
              <div key={i}>{issue}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
