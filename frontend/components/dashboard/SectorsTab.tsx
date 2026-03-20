"use client";

import { useState, useEffect } from "react";
import { BarChart3, TrendingUp, TrendingDown, Shield, Zap } from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";
import { API_URL } from "@/lib/constants";

interface SectorData {
  etf: string;
  name: string;
  price: number;
  ret_5d: number;
  ret_20d: number;
  ret_60d: number;
  ret_ytd: number;
  mr_wr: number;
  mr_trades: number;
  mr_avg_ret: number;
  rsi14: number;
  above_sma50: boolean;
  trend: string;
}

interface PortfolioExposure {
  sector: string;
  tickers: string[];
  cost: number;
  value: number;
  weight: number;
}

interface SectorsResponse {
  sectors: SectorData[];
  portfolio_exposure: PortfolioExposure[];
  total_sectors_used: number;
  total_sectors: number;
  market_regime?: any;
}

const pnlColor = (v: number) => v > 0 ? "text-signal-buy" : v < 0 ? "text-signal-sell" : "text-neutral-400";

export function SectorsTab() {
  const [data, setData] = useState<SectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_URL}/api/v2/sectors`, { cache: "no-store", headers: { "Content-Type": "application/json" } })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-neutral-500">Loading sectors...</div>;
  if (!data) return <div className="p-8 text-neutral-500">No sector data</div>;

  const { sectors, portfolio_exposure } = data;

  return (
    <div className="flex flex-col gap-6 p-4 lg:p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-neutral-100">Sector Analysis</h2>
          <p className="text-xs text-neutral-500">
            11 GICS sectors · {data.total_sectors_used}/{data.total_sectors} in portfolio
          </p>
        </div>
      </div>

      {/* Portfolio Exposure */}
      <div className="rounded-lg border border-neutral-800 p-4">
        <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Portfolio Sector Exposure
        </h3>
        <div className="space-y-2">
          {portfolio_exposure.map(exp => (
            <div key={exp.sector} className="flex items-center gap-3">
              <div className="w-28 text-xs text-neutral-400">{exp.sector}</div>
              <div className="flex-1 h-4 bg-neutral-800 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full", exp.weight > 30 ? "bg-signal-sell" : exp.weight > 20 ? "bg-amber-500" : "bg-signal-buy")}
                  style={{ width: `${Math.min(exp.weight, 100)}%` }}
                />
              </div>
              <div className="w-12 text-right text-xs font-medium text-neutral-300">{exp.weight.toFixed(0)}%</div>
              <div className="w-32 text-[10px] text-neutral-600">{exp.tickers.join(", ")}</div>
            </div>
          ))}
          {/* Missing sectors */}
          {["Financials", "Consumer Disc", "Consumer Staples", "Materials", "Utilities", "Real Estate"].filter(
            s => !portfolio_exposure.some(e => e.sector === s)
          ).map(s => (
            <div key={s} className="flex items-center gap-3 opacity-40">
              <div className="w-28 text-xs text-neutral-600">{s}</div>
              <div className="flex-1 h-4 bg-neutral-800 rounded-full" />
              <div className="w-12 text-right text-xs text-neutral-700">0%</div>
              <div className="w-32 text-[10px] text-neutral-700">&mdash;</div>
            </div>
          ))}
        </div>
      </div>

      {/* Sector Heatmap */}
      <div className="rounded-lg border border-neutral-800 p-4">
        <h3 className="text-sm font-semibold text-neutral-300 mb-3 flex items-center gap-2">
          <BarChart3 className="h-4 w-4" />
          Sector Performance + MR Opportunity
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-neutral-500 border-b border-neutral-800">
                <th className="text-left py-2 px-2">Sector</th>
                <th className="text-right px-2">Price</th>
                <th className="text-right px-2">5d</th>
                <th className="text-right px-2">20d</th>
                <th className="text-right px-2">YTD</th>
                <th className="text-right px-2">60d</th>
                <th className="text-center px-2">Trend</th>
                <th className="text-right px-2">MR WR</th>
                <th className="text-right px-2">MR Ret</th>
                <th className="text-center px-2">Signal</th>
              </tr>
            </thead>
            <tbody>
              {sectors.map(s => {
                const inPortfolio = portfolio_exposure.some(e => e.sector === s.name);
                return (
                  <tr key={s.etf} className={cn("border-b border-neutral-800/50 hover:bg-neutral-800/30", inPortfolio && "bg-blue-500/5")}>
                    <td className="py-2.5 px-2">
                      <div className="font-medium text-neutral-200">{s.name}</div>
                      <div className="text-neutral-600">{s.etf}</div>
                    </td>
                    <td className="text-right px-2 text-neutral-300">{formatCurrency(s.price)}</td>
                    <td className={cn("text-right px-2 font-medium", pnlColor(s.ret_5d))}>{s.ret_5d > 0 ? "+" : ""}{s.ret_5d.toFixed(1)}%</td>
                    <td className={cn("text-right px-2 font-medium", pnlColor(s.ret_20d))}>{s.ret_20d > 0 ? "+" : ""}{s.ret_20d.toFixed(1)}%</td>
                    <td className={cn("text-right px-2 font-bold", pnlColor(s.ret_ytd))}>{s.ret_ytd > 0 ? "+" : ""}{s.ret_ytd.toFixed(1)}%</td>
                    <td className={cn("text-right px-2 font-medium", pnlColor(s.ret_60d ?? 0))}>{(s.ret_60d ?? 0) > 0 ? "+" : ""}{(s.ret_60d ?? 0).toFixed(1)}%</td>
                    <td className="text-center px-2">
                      <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded",
                        s.trend === "BULL" ? "bg-signal-buy/20 text-signal-buy" :
                        s.trend === "BEAR" ? "bg-signal-sell/20 text-signal-sell" :
                        "bg-neutral-800 text-neutral-400"
                      )}>{s.trend}</span>
                    </td>
                    <td className={cn("text-right px-2", s.mr_wr >= 60 ? "text-signal-buy" : s.mr_wr >= 50 ? "text-amber-400" : "text-signal-sell")}>
                      {s.mr_wr.toFixed(0)}%
                      <span className="text-neutral-600 ml-1">({s.mr_trades}t)</span>
                    </td>
                    <td className={cn("text-right px-2", pnlColor(s.mr_avg_ret))}>{s.mr_avg_ret > 0 ? "+" : ""}{s.mr_avg_ret.toFixed(2)}%</td>
                    <td className="text-center px-2">
                      {s.ret_ytd > 10 && s.mr_wr >= 55 ? (
                        <span className="text-signal-buy text-[10px] font-bold">STRONG</span>
                      ) : s.mr_wr >= 60 ? (
                        <span className="text-amber-400 text-[10px]">MR OK</span>
                      ) : s.ret_ytd > 15 ? (
                        <span className="text-blue-400 text-[10px]">MOMENTUM</span>
                      ) : (
                        <span className="text-neutral-600 text-[10px]">WEAK</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
