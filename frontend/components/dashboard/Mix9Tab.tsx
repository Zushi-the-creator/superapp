"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Mix9State } from "@/lib/types";

/** MIX9 — the live entry/exit engine (regime-switching, 30% XLK core).
 *
 * MIX9 is DD-parked ~55% of the time, so an empty sleeve is its NORMAL state,
 * not a broken feed. The tab therefore always shows the queued entries — the
 * names the sleeve buys the moment the active strategy climbs back above its
 * -15% threshold — and says plainly which state it is in.
 */


const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export function Mix9Tab() {
  const [s, setS] = useState<Mix9State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.getMix9State()
      .then(d => { setS(d); setErr(null); })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  if (loading && !s) return <div className="p-6 text-neutral-400">Loading MIX9…</div>;
  if (err) return (
    <div className="p-6">
      <div className="rounded border border-red-800 bg-red-950/40 p-4 text-red-300">
        MIX9 unavailable: {err}
        <button onClick={load} className="ml-3 rounded bg-red-800 px-3 py-1 text-xs text-white">Retry</button>
      </div>
    </div>
  );
  if (s?.pending) return (
    <div className="p-6">
      <div className="rounded border border-amber-800 bg-amber-950/40 p-4 text-amber-200">
        {s.message ?? "No MIX9 snapshot yet."}
      </div>
    </div>
  );

  const t = s?.target;
  if (!t) return <div className="p-6 text-neutral-400">No MIX9 target.</div>;
  const queued = (t.preview_sleeve?.length ? t.preview_sleeve : t.sleeve) ?? [];
  const live = !t.parked;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      {/* header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-neutral-100">Entries — MIX9</h1>
          <p className="text-sm text-neutral-400">
            {t.asof} · regime <span className="text-neutral-200">{t.regime}</span> →{" "}
            <span className="text-neutral-200">{t.active_strategy}</span>
            {s?.computed_at && <span className="text-neutral-600"> · snapshot {s.computed_at}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded px-2 py-1 text-xs font-medium ${
            s?.engine?.enabled ? "bg-emerald-900 text-emerald-200" : "bg-neutral-800 text-neutral-400"}`}>
            {s?.engine?.enabled ? "AUTO ON" : "ADVISORY"}
          </span>
          <button onClick={load} className="rounded bg-neutral-800 px-3 py-1 text-xs text-neutral-200">
            Refresh
          </button>
        </div>
      </div>

      {/* state banner — parked is normal, say so */}
      <div className={`rounded border p-4 ${live
        ? "border-emerald-800 bg-emerald-950/30" : "border-amber-800 bg-amber-950/30"}`}>
        <div className="flex items-baseline gap-3">
          <span className={`text-sm font-semibold ${live ? "text-emerald-300" : "text-amber-300"}`}>
            {live ? "SLEEVE ACTIVE" : "SLEEVE PARKED IN CORE"}
          </span>
          <span className="text-xs text-neutral-400">
            {t.active_strategy} is {t.dd_pct?.toFixed(1)}% from its own peak (stop −{t.dd_stop_pct}%)
          </span>
        </div>
        <p className="mt-1 text-xs text-neutral-400">
          {live
            ? "The 70% sleeve is deployed in the names below."
            : `The 70% sleeve sits in ${t.core.ticker} until ${t.active_strategy} recovers above −${t.dd_stop_pct}%. This is MIX9's normal state roughly 55% of the time — not a broken feed.`}
        </p>
      </div>

      {/* allocation */}
      <div className="grid grid-cols-3 gap-3">
        {[["Equity", money(t.equity_usd)],
          [`Core (${t.core.ticker})`, `${money(t.core.target_usd)} · ${t.core.shares} sh`],
          ["Sleeve", t.sleeve_usd > 0 ? money(t.sleeve_usd) : "parked"]].map(([k, v]) => (
          <div key={k} className="rounded border border-neutral-800 bg-neutral-900 p-3">
            <div className="text-xs text-neutral-500">{k}</div>
            <div className="mt-1 text-sm font-medium text-neutral-100">{v}</div>
          </div>
        ))}
      </div>

      {/* trades */}
      {!!s?.trades?.length && (
        <div className="rounded border border-neutral-800">
          <div className="border-b border-neutral-800 px-4 py-2 text-sm font-medium text-neutral-200">
            Trades to reach target
            <span className="ml-2 text-xs font-normal text-neutral-500">advisory — nothing auto-executes</span>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {s.trades.map(x => (
                <tr key={x.ticker} className="border-b border-neutral-900 last:border-0">
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      x.side === "BUY" ? "bg-emerald-900 text-emerald-200" : "bg-red-900 text-red-200"}`}>
                      {x.side}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-medium text-neutral-100">{x.ticker}</td>
                  <td className="px-4 py-2 text-right text-neutral-200">{money(x.usd)}</td>
                  <td className="px-4 py-2 text-right text-xs text-neutral-500">
                    {money(x.current_usd)} → {money(x.target_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ENTRIES — the queue, shown whether live or parked */}
      <div className="rounded border border-neutral-800">
        <div className="border-b border-neutral-800 px-4 py-2">
          <span className="text-sm font-medium text-neutral-200">
            {live ? "Entries — held now" : "Entries — queued for when the regime is ready"}
          </span>
          <span className="ml-2 text-xs text-neutral-500">
            {t.active_strategy} top-{queued.length}, equal weight, monthly rebalance
          </span>
        </div>
        {queued.length === 0 ? (
          <div className="px-4 py-6 text-sm text-neutral-500">
            No candidates pass {t.active_strategy}&apos;s filter today.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-4 py-2 text-left">#</th>
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-right">Price</th>
                <th className="px-4 py-2 text-right">Target</th>
                <th className="px-4 py-2 text-right">Shares</th>
              </tr>
            </thead>
            <tbody>
              {queued.map((p, i) => (
                <tr key={p.ticker} className={`border-b border-neutral-900 last:border-0 ${
                  live ? "" : "opacity-60"}`}>
                  <td className="px-4 py-2 text-neutral-600">{i + 1}</td>
                  <td className="px-4 py-2 font-medium text-neutral-100">{p.ticker}</td>
                  <td className="px-4 py-2 text-right text-neutral-300">${p.price}</td>
                  <td className="px-4 py-2 text-right text-neutral-300">{money(p.target_usd)}</td>
                  <td className="px-4 py-2 text-right text-neutral-400">{p.shares}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* component drawdowns — why it's parked */}
      <div className="rounded border border-neutral-800">
        <div className="border-b border-neutral-800 px-4 py-2 text-sm font-medium text-neutral-200">
          Component drawdowns
          <span className="ml-2 text-xs font-normal text-neutral-500">
            each strategy vs its own peak · sleeve parks below −{t.dd_stop_pct}%
          </span>
        </div>
        <div className="divide-y divide-neutral-900">
          {Object.entries(t.components ?? {}).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between px-4 py-2 text-sm">
              <span className={k === t.active_strategy ? "font-medium text-neutral-100" : "text-neutral-400"}>
                {k}{k === t.active_strategy && <span className="ml-2 text-xs text-blue-400">ACTIVE</span>}
              </span>
              <span className="flex items-center gap-3">
                <span className={v.dd_pct < -15 ? "text-amber-400" : "text-neutral-300"}>
                  {v.dd_pct.toFixed(1)}%
                </span>
                {v.parked && <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">PARKED</span>}
              </span>
            </div>
          ))}
        </div>
      </div>

      {s?.engine?.note && (
        <p className="text-xs leading-relaxed text-neutral-500">{s.engine.note}</p>
      )}
    </div>
  );
}
