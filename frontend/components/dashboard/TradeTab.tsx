"use client";

import { useState } from "react";
import { Header } from "@/components/layout/Header";
import { useData } from "@/components/providers/DataProvider";
import { api } from "@/lib/api";
import { formatCurrency, cn, pnlColor } from "@/lib/utils";
import { CheckCircle, XCircle } from "lucide-react";
import type { PositionDetail, TradeResult } from "@/lib/types";

export function TradeTab() {
  const { portfolio, refreshAll } = useData();
  const { data, lastUpdated, loading } = portfolio;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Trade"
        lastUpdated={lastUpdated}
        loading={loading}
        onRefresh={refreshAll}
      />
      <div className="flex-1 overflow-y-auto p-4 md:p-6 pb-20 md:pb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
          <BuyForm onComplete={refreshAll} />
          <SellForm
            positions={data?.positions ?? []}
            onComplete={refreshAll}
          />
          <DepositForm onComplete={refreshAll} />
        </div>
      </div>
    </div>
  );
}

function BuyForm({ onComplete }: { onComplete: () => Promise<void> }) {
  const [ticker, setTicker] = useState("");
  const [shares, setShares] = useState("");
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<TradeResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const total = (parseFloat(shares) || 0) * (parseFloat(price) || 0);
  const fee = 1.5;

  const handleSubmit = async () => {
    if (!ticker || !shares || !price) return;
    setSubmitting(true);
    try {
      const res = await api.buy(
        ticker,
        parseFloat(shares),
        parseFloat(price),
        notes
      );
      setResult(res);
      if (res.success) {
        setTicker("");
        setShares("");
        setPrice("");
        setNotes("");
        await onComplete();
      }
    } catch (e) {
      setResult({
        success: false,
        message: e instanceof Error ? e.message : "Failed",
        ticker,
        shares: 0,
        price: 0,
        total: 0,
        fee: 0,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
      <h3 className="text-sm font-semibold text-signal-buy mb-4">BUY</h3>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-neutral-500">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-buy focus:outline-none"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-neutral-500">Shares</label>
            <input
              type="number"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              placeholder="0.00"
              step="0.0001"
              className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-buy focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-neutral-500">Price</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="0.00"
              step="0.01"
              className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-buy focus:outline-none"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-neutral-500">Notes (optional)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-buy focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-between text-xs text-neutral-400 pt-2">
          <span>Fee: {formatCurrency(fee)}</span>
          <span>Total: {formatCurrency(total + fee)}</span>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting || !ticker || !shares || !price}
          className="w-full py-2.5 rounded-lg bg-signal-buy text-white font-medium text-sm hover:bg-signal-buy/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "Processing..." : "CONFIRM BUY"}
        </button>
      </div>

      <ResultMessage result={result} />
    </div>
  );
}

function SellForm({
  positions,
  onComplete,
}: {
  positions: PositionDetail[];
  onComplete: () => Promise<void>;
}) {
  const [selected, setSelected] = useState("");
  const [shares, setShares] = useState("");
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<TradeResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const pos = positions.find((p) => p.ticker === selected);
  const total = (parseFloat(shares) || 0) * (parseFloat(price) || 0);
  const fee = 1.5;
  const pnl = pos
    ? ((parseFloat(price) || 0) - pos.entry_price) * (parseFloat(shares) || 0) - fee
    : 0;

  const handleSubmit = async () => {
    if (!selected || !shares || !price) return;
    setSubmitting(true);
    try {
      const res = await api.sell(
        selected,
        parseFloat(shares),
        parseFloat(price),
        notes
      );
      setResult(res);
      if (res.success) {
        setSelected("");
        setShares("");
        setPrice("");
        setNotes("");
        await onComplete();
      }
    } catch (e) {
      setResult({
        success: false,
        message: e instanceof Error ? e.message : "Failed",
        ticker: selected,
        shares: 0,
        price: 0,
        total: 0,
        fee: 0,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
      <h3 className="text-sm font-semibold text-signal-sell mb-4">SELL</h3>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-neutral-500">Position</label>
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              const p = positions.find((x) => x.ticker === e.target.value);
              if (p) {
                setShares(p.shares.toFixed(4));
                setPrice(p.current_price.toFixed(2));
              }
            }}
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-sell focus:outline-none"
          >
            <option value="">Select position...</option>
            {positions.map((p) => (
              <option key={p.ticker} value={p.ticker}>
                {p.ticker} - {p.shares.toFixed(4)} shares @ {formatCurrency(p.entry_price)}
              </option>
            ))}
          </select>
        </div>

        {pos && (
          <div className="rounded-lg bg-neutral-800/50 p-3 text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-neutral-500">Entry</span>
              <span className="text-neutral-300">
                {formatCurrency(pos.entry_price)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Current P&L</span>
              <span className={pnlColor(pos.pnl)}>
                {formatCurrency(pos.pnl)} ({pos.pnl_pct.toFixed(2)}%)
              </span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-neutral-500">Shares</label>
            <input
              type="number"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              step="0.0001"
              className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-sell focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-neutral-500">Price</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              step="0.01"
              className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-sell focus:outline-none"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-neutral-500">Notes (optional)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-signal-sell focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-between text-xs text-neutral-400 pt-2">
          <span>Fee: {formatCurrency(fee)}</span>
          <div className="text-right">
            <div>Total: {formatCurrency(total)}</div>
            {pos && (
              <div className={pnlColor(pnl)}>
                Realized: {formatCurrency(pnl)}
              </div>
            )}
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting || !selected || !shares || !price}
          className="w-full py-2.5 rounded-lg bg-signal-sell text-white font-medium text-sm hover:bg-signal-sell/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "Processing..." : "CONFIRM SELL"}
        </button>
      </div>

      <ResultMessage result={result} />
    </div>
  );
}

function DepositForm({ onComplete }: { onComplete: () => Promise<void> }) {
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  const handleSubmit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return;
    setSubmitting(true);
    try {
      const res = await api.deposit(amt, date || undefined, notes);
      setResult({ success: res.success, message: res.message });
      if (res.success) {
        setAmount("");
        setDate("");
        setNotes("");
        await onComplete();
      }
    } catch (e) {
      setResult({ success: false, message: e instanceof Error ? e.message : "Failed" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
      <h3 className="text-sm font-semibold text-amber-400 mb-4">DEPOSIT (new capital)</h3>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-neutral-500">Amount (USD)</label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            step="0.01"
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-amber-400 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-xs text-neutral-500">Date (optional, defaults to today)</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-amber-400 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-xs text-neutral-500">Notes (optional)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full mt-1 px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-100 text-sm focus:border-amber-400 focus:outline-none"
          />
        </div>
        <button
          onClick={handleSubmit}
          disabled={submitting || !amount}
          className="w-full py-2.5 rounded-lg bg-amber-500 text-black font-medium text-sm hover:bg-amber-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "Recording..." : "RECORD DEPOSIT"}
        </button>
      </div>
      {result && (
        <div
          className={cn(
            "mt-3 p-3 rounded-lg flex items-center gap-2 text-xs",
            result.success ? "bg-amber-500/10 text-amber-400" : "bg-signal-sell/10 text-signal-sell"
          )}
        >
          {result.success ? <CheckCircle className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
          {result.message}
        </div>
      )}
    </div>
  );
}


function ResultMessage({ result }: { result: TradeResult | null }) {
  if (!result) return null;

  return (
    <div
      className={cn(
        "mt-3 p-3 rounded-lg flex items-center gap-2 text-xs",
        result.success
          ? "bg-signal-buy/10 text-signal-buy"
          : "bg-signal-sell/10 text-signal-sell"
      )}
    >
      {result.success ? (
        <CheckCircle className="h-4 w-4 shrink-0" />
      ) : (
        <XCircle className="h-4 w-4 shrink-0" />
      )}
      {result.message}
    </div>
  );
}
