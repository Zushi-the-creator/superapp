"use client";

import { useData } from "@/components/providers/DataProvider";
import { Header } from "@/components/layout/Header";
import { formatCurrency, formatDateFull, cn, pnlColor } from "@/lib/utils";

export function HistoryTab() {
  const { history } = useData();
  const { data, loading, lastUpdated, refresh } = history;

  const transactions = data?.transactions ?? [];

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Trade History"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 pb-20 md:pb-6">
        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <span className="text-xs text-neutral-500">Total Trades</span>
            <div className="text-xl font-bold text-neutral-200">
              {data?.trade_count ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <span className="text-xs text-neutral-500">Realized P&L</span>
            <div
              className={cn(
                "text-xl font-bold",
                pnlColor(data?.total_realized_pnl ?? 0)
              )}
            >
              {formatCurrency(data?.total_realized_pnl ?? 0)}
            </div>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
            <span className="text-xs text-neutral-500">Total Fees</span>
            <div className="text-xl font-bold text-signal-sell">
              {formatCurrency(data?.total_fees ?? 0)}
            </div>
          </div>
        </div>

        {/* Transaction table */}
        {transactions.length === 0 && !loading && (
          <div className="rounded-xl border border-neutral-800 p-8 text-center text-neutral-500">
            No transactions recorded yet.
          </div>
        )}

        {transactions.length > 0 && (
          <div className="rounded-xl border border-neutral-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900/50">
                  <th className="text-left px-4 py-3 text-xs text-neutral-500 font-medium">
                    Date
                  </th>
                  <th className="text-left px-3 py-3 text-xs text-neutral-500 font-medium">
                    Action
                  </th>
                  <th className="text-left px-3 py-3 text-xs text-neutral-500 font-medium">
                    Ticker
                  </th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">
                    Price
                  </th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">
                    Shares
                  </th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium">
                    Total
                  </th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">
                    Fee
                  </th>
                  <th className="text-right px-3 py-3 text-xs text-neutral-500 font-medium hidden md:table-cell">
                    P&L
                  </th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr
                    key={tx.id}
                    className="border-b border-neutral-800/50 hover:bg-neutral-800/30"
                  >
                    <td className="px-4 py-3 text-neutral-400 text-xs">
                      {formatDateFull(tx.date)}
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={cn(
                          "inline-flex px-2 py-0.5 rounded text-xs font-medium",
                          tx.action === "BUY"
                            ? "bg-signal-buy/15 text-signal-buy"
                            : "bg-signal-sell/15 text-signal-sell"
                        )}
                      >
                        {tx.action}
                      </span>
                    </td>
                    <td className="px-3 py-3 font-medium text-neutral-200">
                      {tx.ticker}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-300">
                      {formatCurrency(tx.price)}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-400">
                      {tx.shares.toFixed(4)}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-300">
                      {formatCurrency(tx.total)}
                    </td>
                    <td className="text-right px-3 py-3 text-neutral-500 hidden md:table-cell">
                      {formatCurrency(tx.fee)}
                    </td>
                    <td
                      className={cn(
                        "text-right px-3 py-3 font-medium hidden md:table-cell",
                        tx.realized_pnl !== null
                          ? pnlColor(tx.realized_pnl)
                          : "text-neutral-500"
                      )}
                    >
                      {tx.realized_pnl !== null
                        ? formatCurrency(tx.realized_pnl)
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
