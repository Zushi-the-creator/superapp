"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Ban,
  Bot,
  Check,
  Clock,
  Hand,
  Play,
  RefreshCw,
  Repeat,
  Scale,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  SimCandidate,
  SimCandidatesResponse,
  SimDecision,
  SimEquityPoint,
  SimHistoryResponse,
  SimPosition,
  SimState,
  SimStrategy,
  SimTradeStats,
} from "@/lib/types";
import { cn, formatCurrency, formatPercent, pnlColor } from "@/lib/utils";
import { CardSkeleton, TableSkeleton } from "@/components/shared/Skeleton";

type SubTab = "book" | "strategies" | "candidates" | "journal" | "history" | "policy";

const DECISION_STYLE: Record<string, { icon: React.ElementType; cls: string }> = {
  ENTRY: { icon: TrendingUp, cls: "text-signal-buy" },
  EXIT: { icon: TrendingDown, cls: "text-orange-400" },
  SWITCH: { icon: Repeat, cls: "text-purple-400" },
  MANUAL: { icon: Hand, cls: "text-cyan-400" },
  REBALANCE: { icon: Scale, cls: "text-blue-400" },
  SKIP: { icon: Ban, cls: "text-neutral-500" },
  PAUSE: { icon: ShieldAlert, cls: "text-amber-400" },
  HOLD: { icon: Clock, cls: "text-neutral-500" },
  CYCLE: { icon: Activity, cls: "text-neutral-600" },
};

const TIER_STYLE: Record<string, string> = {
  A: "border-signal-buy/40 bg-signal-buy/10 text-signal-buy",
  B: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  C: "border-neutral-600 bg-neutral-800 text-neutral-400",
};

const TIER_MEANING: Record<string, string> = {
  A: "Walk-forward validated on our own data",
  B: "Study-supported, not yet walk-forward validated here",
  C: "Documented as weak or unvalidated",
};

export function SimTab() {
  const [state, setState] = useState<SimState | null>(null);
  const [decisions, setDecisions] = useState<SimDecision[]>([]);
  const [history, setHistory] = useState<SimHistoryResponse | null>(null);
  const [sub, setSub] = useState<SubTab>("book");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, d, h] = await Promise.all([
        api.getSimState(),
        api.getSimDecisions(200),
        api.getSimHistory(200),
      ]);
      setState(s);
      setDecisions(d.decisions);
      setHistory(h);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load simulation");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const runCycle = async (force: boolean) => {
    setRunning(true);
    try {
      await api.runSimCycle(force);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cycle failed");
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col gap-6 p-4 lg:p-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (error && !state) {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-lg border border-signal-sell/30 bg-signal-sell/5 p-6 text-center">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-signal-sell" />
          <div className="mb-1 text-sm font-semibold text-neutral-200">
            Couldn&apos;t load the simulation
          </div>
          <div className="mb-4 text-xs text-neutral-500">{error}</div>
          <button
            onClick={() => {
              setLoading(true);
              load();
            }}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-800 px-4 py-2 text-xs font-medium text-neutral-200 hover:bg-neutral-700"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Retry
          </button>
        </div>
      </div>
    );
  }

  if (!state) return <div className="p-8 text-neutral-500">No simulation data</div>;

  const regime = (state.regime?.regime as string) || "UNKNOWN";
  const paused = Boolean(state.regime?.pause_entries);
  const activeStrats = state.strategies.filter((s) => s.enabled);

  return (
    <div className="flex h-full flex-col overflow-y-auto pb-20 md:pb-0">
      <div className="flex flex-col gap-5 p-4 lg:p-6">
        {error && (
          <div className="flex items-center justify-between rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            <span className="flex items-center gap-2">
              <AlertCircle className="h-3.5 w-3.5" /> Refresh failed — showing last loaded data
            </span>
            <button onClick={load} className="flex items-center gap-1 font-medium hover:text-amber-200">
              <RefreshCw className="h-3 w-3" /> Retry
            </button>
          </div>
        )}

        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-neutral-100">
              <Bot className="h-5 w-5 text-signal-buy" />
              Simulator — $100k, {activeStrats.length} strategies
            </h2>
            <p className="mt-1 max-w-2xl text-xs text-neutral-500">
              Model-managed paper book, completely separate from the live portfolio. Runs every{" "}
              {state.config.cycle_minutes} min during market hours. You can also buy or switch by
              hand — manual trades are tracked separately so you can see whether they help.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "rounded-md border px-2 py-1 text-[11px] font-medium",
                paused
                  ? "border-signal-sell/30 bg-signal-sell/10 text-signal-sell"
                  : "border-neutral-700 bg-neutral-800/60 text-neutral-300"
              )}
            >
              {regime}
              {paused ? " · ENTRIES PAUSED" : ` · ${state.regime?.position_size_pct ?? 100}% size`}
            </span>
            <span className="rounded-md border border-neutral-700 bg-neutral-800/60 px-2 py-1 text-[11px] text-neutral-400">
              {state.market_session}
            </span>
            <button
              onClick={() => runCycle(state.market_session !== "REGULAR")}
              disabled={running || state.cycle_running}
              className="inline-flex items-center gap-1.5 rounded-md bg-neutral-800 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
              title={
                state.market_session === "REGULAR"
                  ? "Run a decision cycle now"
                  : "Market closed — forces fills at the last known price"
              }
            >
              {running || state.cycle_running ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Run cycle
            </button>
          </div>
        </div>

        {/* KPIs */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi
            label="Equity"
            value={formatCurrency(state.equity)}
            sub={`from ${formatCurrency(state.starting_capital)} · ${state.days_live}d live`}
          />
          <Kpi
            label="Total P&L"
            value={formatCurrency(state.total_pnl)}
            sub={formatPercent(state.roi_pct)}
            tone={state.total_pnl}
          />
          <Kpi
            label={`vs ${state.bench_ticker} buy & hold`}
            value={
              state.bench_equity
                ? `${state.alpha_vs_bench_pp >= 0 ? "+" : ""}${state.alpha_vs_bench_pp.toFixed(2)}pp`
                : "—"
            }
            sub={
              state.bench_equity
                ? `${state.bench_ticker} ${formatPercent(state.bench_roi_pct)}`
                : "benchmark starts at first snapshot"
            }
            tone={state.bench_equity ? state.alpha_vs_bench_pp : 0}
          />
          <Kpi
            label="Realized track record"
            value={
              state.stats.closed_trades
                ? `${state.stats.win_rate.toFixed(0)}% WR`
                : "No closed trades"
            }
            sub={
              state.stats.closed_trades
                ? `${state.stats.closed_trades} trades · avg ${formatPercent(
                    state.stats.avg_return_pct
                  )} · MDD ${state.stats.max_drawdown_pct.toFixed(1)}%`
                : "waiting on the first exit"
            }
          />
        </div>

        <StrategyBar strategies={state.strategies} cashPct={state.cash_pct} cash={state.cash} />

        <EquityChart curve={state.equity_curve} start={state.starting_capital} bench={state.bench_ticker} />

        {/* Sub-tabs */}
        <div className="flex flex-wrap gap-1 border-b border-neutral-800">
          {(
            [
              ["book", `Book (${state.positions.length})`],
              ["strategies", `Strategies (${activeStrats.length}/${state.strategies.length})`],
              ["candidates", "Buy / Switch"],
              ["journal", `Journal (${decisions.length})`],
              ["history", `Closed (${history?.closed_positions.length ?? 0})`],
              ["policy", "Policy"],
            ] as [SubTab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setSub(id)}
              className={cn(
                "px-3 py-2 text-xs font-medium transition-colors",
                sub === id
                  ? "border-b-2 border-signal-buy text-neutral-100"
                  : "text-neutral-500 hover:text-neutral-300"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {sub === "book" && <BookTable positions={state.positions} onChanged={load} />}
        {sub === "strategies" && <StrategiesPanel state={state} onSaved={load} />}
        {sub === "candidates" && <CandidatesPanel state={state} onTraded={load} />}
        {sub === "journal" && <Journal decisions={decisions} />}
        {sub === "history" && <ClosedTable history={history} strategies={state.strategies} />}
        {sub === "policy" && <PolicyPanel state={state} onSaved={load} />}
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: number;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={cn("mt-1 text-xl font-semibold", tone === undefined ? "text-neutral-100" : pnlColor(tone))}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-neutral-500">{sub}</div>}
    </div>
  );
}

function TierBadge({ tier }: { tier: string }) {
  return (
    <span
      title={TIER_MEANING[tier]}
      className={cn("rounded border px-1.5 py-0.5 text-[10px] font-medium", TIER_STYLE[tier])}
    >
      Tier {tier}
    </span>
  );
}

const SLEEVE_COLORS = [
  "bg-blue-500/70",
  "bg-signal-buy/70",
  "bg-purple-500/70",
  "bg-amber-500/70",
  "bg-cyan-500/70",
  "bg-pink-500/70",
];

/** Capital split across the live strategies — the "which strategy are we using" bar. */
function StrategyBar({
  strategies,
  cashPct,
  cash,
}: {
  strategies: SimStrategy[];
  cashPct: number;
  cash: number;
}) {
  const live = strategies.filter((s) => s.weight_pct > 0 || s.enabled);
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="mb-2 flex items-center justify-between text-xs text-neutral-400">
        <span>Capital by strategy</span>
        <span className="text-neutral-500">{live.filter((s) => s.enabled).length} running</span>
      </div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-neutral-800">
        {live.map((s, i) => (
          <div
            key={s.id}
            className={SLEEVE_COLORS[i % SLEEVE_COLORS.length]}
            style={{ width: `${s.weight_pct}%` }}
            title={`${s.label}: ${s.weight_pct.toFixed(1)}%`}
          />
        ))}
        <div className="bg-neutral-700" style={{ width: `${cashPct}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-neutral-400">
        {live.map((s, i) => (
          <span key={s.id} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-sm", SLEEVE_COLORS[i % SLEEVE_COLORS.length])} />
            {s.short}
            <span className="text-neutral-300">
              {s.weight_pct.toFixed(1)}% · {formatCurrency(s.value)}
            </span>
            <span className="text-neutral-600">
              ({s.open_positions}
              {s.kind === "ALPHA" ? `/${s.slots}` : ""})
            </span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-neutral-700" />
          Cash <span className="text-neutral-300">{cashPct.toFixed(1)}% · {formatCurrency(cash)}</span>
        </span>
      </div>
    </div>
  );
}

/** Equity curve vs benchmark. Plain SVG — no chart lib, matches the rest of the app. */
function EquityChart({
  curve,
  start,
  bench,
}: {
  curve: SimEquityPoint[];
  start: number;
  bench: string;
}) {
  const pts = useMemo(() => curve.filter((c) => c.equity > 0), [curve]);
  if (pts.length < 2) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-center text-xs text-neutral-500">
        Equity curve builds one point per trading day — {pts.length} snapshot
        {pts.length === 1 ? "" : "s"} so far.
      </div>
    );
  }

  const W = 1000;
  const H = 180;
  const values = pts.flatMap((p) => [p.equity, p.bench_equity || start]);
  const lo = Math.min(...values, start);
  const hi = Math.max(...values, start);
  const pad = (hi - lo) * 0.08 || start * 0.01;
  const y = (v: number) => H - ((v - (lo - pad)) / (hi - lo + pad * 2)) * H;
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const path = (get: (p: SimEquityPoint) => number) =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(get(p)).toFixed(1)}`).join(" ");

  const last = pts[pts.length - 1];
  const up = last.equity >= start;

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="text-neutral-400">Equity vs {bench} buy &amp; hold</span>
        <span className="flex gap-3 text-[11px]">
          <span className={up ? "text-signal-buy" : "text-signal-sell"}>
            ● Sim {formatCurrency(last.equity)}
          </span>
          {last.bench_equity > 0 && (
            <span className="text-neutral-400">● {bench} {formatCurrency(last.bench_equity)}</span>
          )}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full" preserveAspectRatio="none">
        <line
          x1={0}
          x2={W}
          y1={y(start)}
          y2={y(start)}
          stroke="currentColor"
          className="text-neutral-700"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
        {pts.some((p) => p.bench_equity > 0) && (
          <path
            d={path((p) => p.bench_equity || start)}
            fill="none"
            stroke="currentColor"
            className="text-neutral-500"
            strokeWidth={1.5}
          />
        )}
        <path
          d={path((p) => p.equity)}
          fill="none"
          stroke="currentColor"
          className={up ? "text-signal-buy" : "text-signal-sell"}
          strokeWidth={2}
        />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-neutral-600">
        <span>{pts[0].date}</span>
        <span>dashed = {formatCurrency(start)} start</span>
        <span>{last.date}</span>
      </div>
    </div>
  );
}

function BookTable({ positions, onChanged }: { positions: SimPosition[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [switchFor, setSwitchFor] = useState<SimPosition | null>(null);

  const close = async (p: SimPosition) => {
    setBusy(p.id);
    try {
      await api.simClosePosition(p.id, `Manual close from the Book tab (day ${p.days_held}/${p.hold_days})`);
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  if (!positions.length) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
        Book is all cash. The engine opens positions on its next cycle when the regime allows and a
        candidate clears the veto chain.
      </div>
    );
  }

  const sorted = [...positions].sort((a, b) =>
    a.sleeve === b.sleeve ? b.value - a.value : a.sleeve === "ALPHA" ? -1 : 1
  );

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="bg-neutral-900/60 text-[11px] uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-3 py-2 text-left">Ticker</th>
              <th className="px-3 py-2 text-left">Strategy</th>
              <th className="px-3 py-2 text-right">Shares</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Now</th>
              <th className="px-3 py-2 text-right">Value</th>
              <th className="px-3 py-2 text-right">P&L</th>
              <th className="px-3 py-2 text-right">Weight</th>
              <th className="px-3 py-2 text-left">Exit rule</th>
              <th className="px-3 py-2 text-right">Act</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {sorted.map((p) => (
              <tr key={p.id} className="hover:bg-neutral-900/40">
                <td className="px-3 py-2 font-medium text-neutral-100">
                  {p.ticker}
                  {p.price_stale && (
                    <span className="ml-1 text-[10px] text-amber-500" title="No live quote — last close">
                      ●
                    </span>
                  )}
                  {p.origin === "MANUAL" && (
                    <span className="ml-1 text-[10px] text-cyan-400" title="Opened manually">
                      ✋
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "rounded border px-1.5 py-0.5 text-[10px]",
                        p.sleeve === "CORE"
                          ? "border-blue-500/30 bg-blue-500/10 text-blue-400"
                          : "border-signal-buy/30 bg-signal-buy/10 text-signal-buy"
                      )}
                      title={p.strategy_label}
                    >
                      {p.strategy_short}
                    </span>
                    <TierBadge tier={p.strategy_tier} />
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                  {p.shares.toFixed(3)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                  ${p.entry_price.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-neutral-200">
                  ${p.current_price.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-neutral-200">
                  {formatCurrency(p.value)}
                </td>
                <td className={cn("px-3 py-2 text-right tabular-nums", pnlColor(p.unrealized_pnl))}>
                  {formatCurrency(p.unrealized_pnl)}
                  <span className="ml-1 text-[11px]">({formatPercent(p.unrealized_pnl_pct)})</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                  {p.weight_pct.toFixed(1)}%
                </td>
                <td className="px-3 py-2 text-xs text-neutral-400">
                  <div>{p.exit_rule}</div>
                  {p.days_remaining !== null ? (
                    <div className="text-[11px] text-neutral-600">
                      day {p.days_held}/{p.hold_days} ·{" "}
                      <span className={p.days_remaining <= 3 ? "text-orange-400" : ""}>
                        {p.days_remaining} left
                      </span>
                    </div>
                  ) : (
                    <div className="text-[11px] text-neutral-600">day {p.days_held}</div>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {p.sleeve === "ALPHA" && (
                    <div className="flex justify-end gap-1">
                      <button
                        onClick={() => setSwitchFor(p)}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300 hover:bg-neutral-800"
                        title="Switch this position into another candidate"
                      >
                        Switch
                      </button>
                      <button
                        onClick={() => close(p)}
                        disabled={busy === p.id}
                        className="rounded border border-signal-sell/30 px-1.5 py-0.5 text-[10px] text-signal-sell hover:bg-signal-sell/10 disabled:opacity-50"
                        title="Sell now, before the exit rule fires"
                      >
                        {busy === p.id ? "…" : "Sell"}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {switchFor && (
        <SwitchDialog
          position={switchFor}
          onClose={() => setSwitchFor(null)}
          onDone={() => {
            setSwitchFor(null);
            onChanged();
          }}
        />
      )}
    </>
  );
}

function SwitchDialog({
  position,
  onClose,
  onDone,
}: {
  position: SimPosition;
  onClose: () => void;
  onDone: () => void;
}) {
  const [data, setData] = useState<SimCandidatesResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSimCandidates(25)
      .then(setData)
      .catch((e) => setErr(e instanceof Error ? e.message : "Failed to load candidates"));
  }, []);

  const doSwitch = async (c: SimCandidate) => {
    setBusy(c.ticker);
    setErr(null);
    try {
      await api.simSwitch(
        position.id,
        c.ticker,
        c.eligible_strategies[0] || position.strategy,
        `Manual switch ${position.ticker} → ${c.ticker}`
      );
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Switch failed");
      setBusy(null);
    }
  };

  const open = (data?.candidates ?? []).filter((c) => !c.held && !c.blocked_reason);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-5">
        <div className="mb-3 flex items-start justify-between">
          <div>
            <div className="text-sm font-semibold text-neutral-100">
              Switch out of {position.ticker}
            </div>
            <div className="text-xs text-neutral-500">
              {position.strategy_label} · day {position.days_held}/{position.hold_days} ·{" "}
              <span className={pnlColor(position.unrealized_pnl)}>
                {formatPercent(position.unrealized_pnl_pct)}
              </span>
            </div>
          </div>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-300">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
          Switching mid-hold tested at −13 to −24 CAGR points vs letting the timer run — the
          position you rotate out of is usually mid-dip, which is the trade working. This will be
          journalled as a manual decision so its cost shows up in the record.
        </div>

        {err && <div className="mb-3 text-xs text-signal-sell">{err}</div>}
        {!data && <div className="text-xs text-neutral-500">Loading candidates…</div>}
        {data && open.length === 0 && (
          <div className="text-xs text-neutral-500">
            No candidate currently clears the gate to switch into.
          </div>
        )}
        <div className="flex flex-col gap-1">
          {open.map((c) => (
            <div
              key={c.ticker}
              className="flex items-center justify-between rounded-md border border-neutral-800 px-3 py-2 hover:bg-neutral-800/40"
            >
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium text-neutral-100">{c.ticker}</span>
                  <span className="text-xs text-neutral-500">${c.price?.toFixed(2)}</span>
                  <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                    score {c.composite_score?.toFixed(0)}
                  </span>
                </div>
                <div className="text-[11px] text-neutral-500">
                  vs held entry score {position.entry_composite.toFixed(0)} ·{" "}
                  {c.eligible_strategies.join(", ")}
                </div>
              </div>
              <button
                onClick={() => doSwitch(c)}
                disabled={busy !== null}
                className="rounded-md bg-purple-500/20 px-3 py-1.5 text-xs font-medium text-purple-300 hover:bg-purple-500/30 disabled:opacity-50"
              >
                {busy === c.ticker ? "Switching…" : "Switch"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StrategiesPanel({ state, onSaved }: { state: SimState; onSaved: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (s: SimStrategy) => {
    setBusy(s.id);
    try {
      await api.setSimConfig({ strategy_enabled: { [s.id]: s.enabled ? 0 : 1 } });
      onSaved();
    } finally {
      setBusy(null);
    }
  };

  const setSlots = async (s: SimStrategy, slots: number) => {
    setBusy(s.id);
    try {
      await api.setSimConfig({ strategy_slots: { [s.id]: Math.max(0, slots) } });
      onSaved();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {state.strategies.map((s) => (
        <div
          key={s.id}
          className={cn(
            "rounded-lg border p-4",
            s.enabled ? "border-neutral-700 bg-neutral-900/60" : "border-neutral-800 bg-neutral-900/20"
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn("text-sm font-semibold", s.enabled ? "text-neutral-100" : "text-neutral-500")}>
                  {s.label}
                </span>
                <TierBadge tier={s.tier} />
                {s.kind === "CORE" && (
                  <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-400">
                    core
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[11px] text-neutral-500">
                Exit: {s.exit_rule}
                {s.kind === "ALPHA" && ` · ${s.open_positions}/${s.slots} slots used`}
                {s.kind === "CORE" && s.target_pct !== null && ` · ${s.target_pct}% target`}
              </div>
            </div>
            <button
              onClick={() => toggle(s)}
              disabled={busy === s.id}
              className={cn(
                "flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors disabled:opacity-50",
                s.enabled ? "bg-signal-buy/60" : "bg-neutral-700"
              )}
            >
              <span
                className={cn(
                  "h-4 w-4 rounded-full bg-neutral-100 transition-transform",
                  s.enabled && "translate-x-4"
                )}
              />
            </button>
          </div>

          <p className="mt-2 text-xs leading-relaxed text-neutral-400">{s.thesis}</p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-neutral-600">
            <span className="text-neutral-500">Evidence:</span> {s.evidence}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-4 border-t border-neutral-800 pt-3 text-[11px]">
            <span className="text-neutral-500">
              Allocated{" "}
              <span className="text-neutral-200">
                {s.weight_pct.toFixed(1)}% · {formatCurrency(s.value)}
              </span>
            </span>
            <span className="text-neutral-500">
              Open P&L{" "}
              <span className={pnlColor(s.unrealized_pnl)}>{formatCurrency(s.unrealized_pnl)}</span>
            </span>
            <span className="text-neutral-500">
              Closed{" "}
              <span className="text-neutral-200">
                {s.stats.closed_trades
                  ? `${s.stats.closed_trades} · ${s.stats.win_rate.toFixed(0)}% WR · avg ${formatPercent(
                      s.stats.avg_return_pct
                    )}`
                  : "none yet"}
              </span>
            </span>
            {s.kind === "ALPHA" && (
              <span className="ml-auto flex items-center gap-1 text-neutral-500">
                slots
                <button
                  onClick={() => setSlots(s, s.slots - 1)}
                  disabled={busy === s.id || s.slots <= 0}
                  className="rounded border border-neutral-700 px-1.5 hover:bg-neutral-800 disabled:opacity-40"
                >
                  −
                </button>
                <span className="w-4 text-center text-neutral-200">{s.slots}</span>
                <button
                  onClick={() => setSlots(s, s.slots + 1)}
                  disabled={busy === s.id}
                  className="rounded border border-neutral-700 px-1.5 hover:bg-neutral-800 disabled:opacity-40"
                >
                  +
                </button>
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function CandidatesPanel({ state, onTraded }: { state: SimState; onTraded: () => void }) {
  const [data, setData] = useState<SimCandidatesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showBlocked, setShowBlocked] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setData(await api.getSimCandidates(40));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load candidates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const buy = async (c: SimCandidate, strategy: string) => {
    setBusy(c.ticker);
    setErr(null);
    try {
      await api.simBuy(c.ticker, strategy, 0, "Manual buy from the Buy/Switch tab");
      await load();
      onTraded();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Buy failed");
    } finally {
      setBusy(null);
    }
  };

  if (loading && !data) return <TableSkeleton rows={6} />;

  const rows = (data?.candidates ?? []).filter((c) => showBlocked || !c.blocked_reason);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-neutral-500">
          Live candidate feed — the same ranked signals the engine sees. Buying here fills at the
          live price and is tagged as a manual decision.
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowBlocked(!showBlocked)}
            className="rounded-md bg-neutral-900 px-2.5 py-1 text-[11px] text-neutral-400 hover:text-neutral-200"
          >
            {showBlocked ? "Hide blocked" : "Show blocked"}
          </button>
          <button
            onClick={load}
            className="inline-flex items-center gap-1.5 rounded-md bg-neutral-800 px-3 py-1.5 text-xs text-neutral-200 hover:bg-neutral-700"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> Refresh
          </button>
        </div>
      </div>

      {err && <div className="text-xs text-signal-sell">{err}</div>}

      {data && data.rotation_ranks.length > 0 && (
        <div className="rounded-md border border-neutral-800 bg-neutral-900/40 px-3 py-2 text-[11px] text-neutral-400">
          <span className="text-neutral-500">12-1 momentum ranks (rotation sleeve):</span>{" "}
          {data.rotation_ranks.slice(0, 10).join(" · ")}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
          No candidates in the feed right now.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full min-w-[1000px] text-sm">
            <thead className="bg-neutral-900/60 text-[11px] uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2 text-left">Ticker</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Score</th>
                <th className="px-3 py-2 text-right">RSI2</th>
                <th className="px-3 py-2 text-right">ATR%</th>
                <th className="px-3 py-2 text-right">WR</th>
                <th className="px-3 py-2 text-left">Analyst</th>
                <th className="px-3 py-2 text-left">Sentiment</th>
                <th className="px-3 py-2 text-left">Buy as</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {rows.map((c) => (
                <tr key={c.ticker} className={cn("hover:bg-neutral-900/40", c.blocked_reason && "opacity-50")}>
                  <td className="px-3 py-2 font-medium text-neutral-100">
                    {c.ticker}
                    <div className="text-[10px] font-normal text-neutral-600">
                      {c.signal_strategy}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-300">
                    ${c.price?.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-200">
                    {c.composite_score?.toFixed(0)}
                    <span className="ml-1 text-[10px] text-neutral-600">{c.quality_tier}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                    {c.rsi2?.toFixed(0)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                    {c.atr_pct?.toFixed(1)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                    {c.win_rate?.toFixed(0)}%
                    <span className="ml-1 text-[10px] text-neutral-600">({c.trades}t)</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-400">{c.analyst_consensus || "—"}</td>
                  <td className="px-3 py-2 text-xs text-neutral-400">{c.sentiment_label || "—"}</td>
                  <td className="px-3 py-2">
                    {c.blocked_reason ? (
                      <span className="text-[11px] text-neutral-500">{c.blocked_reason}</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {c.eligible_strategies.map((sid) => {
                          const meta = state.strategies.find((s) => s.id === sid);
                          return (
                            <button
                              key={sid}
                              onClick={() => buy(c, sid)}
                              disabled={busy !== null}
                              className="rounded border border-signal-buy/30 bg-signal-buy/10 px-1.5 py-0.5 text-[10px] font-medium text-signal-buy hover:bg-signal-buy/20 disabled:opacity-50"
                              title={`Buy into ${meta?.label ?? sid} — exit ${meta?.exit_rule ?? ""}`}
                            >
                              {busy === c.ticker ? "…" : `+ ${meta?.short ?? sid}`}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Journal({ decisions }: { decisions: SimDecision[] }) {
  const [filter, setFilter] = useState<string>("ALL");
  const kinds = ["ALL", "ENTRY", "EXIT", "MANUAL", "SWITCH", "REBALANCE", "SKIP", "PAUSE", "HOLD"];
  const rows = decisions.filter((d) => (filter === "ALL" ? d.kind !== "CYCLE" : d.kind === filter));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1">
        {kinds.map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              filter === k
                ? "bg-neutral-700 text-neutral-100"
                : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"
            )}
          >
            {k}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-center text-xs text-neutral-500">
          No {filter === "ALL" ? "" : filter.toLowerCase() + " "}decisions logged yet.
        </div>
      ) : (
        <div className="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
          {rows.map((d) => {
            const style = DECISION_STYLE[d.kind] ?? DECISION_STYLE.CYCLE;
            const Icon = style.icon;
            return (
              <div key={d.id} className="flex items-start gap-3 px-3 py-2.5 hover:bg-neutral-900/40">
                <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", style.cls)} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className={cn("text-xs font-semibold", style.cls)}>{d.kind}</span>
                    {d.ticker && (
                      <span className="text-sm font-medium text-neutral-100">{d.ticker}</span>
                    )}
                    {d.strategy_label && (
                      <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                        {d.strategy_label}
                      </span>
                    )}
                    {d.composite > 0 && (
                      <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                        score {d.composite.toFixed(0)}
                      </span>
                    )}
                    {d.origin === "MANUAL" && (
                      <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-400">
                        manual
                      </span>
                    )}
                    {d.regime && <span className="text-[10px] text-neutral-600">{d.regime}</span>}
                    <span className="ml-auto text-[10px] tabular-nums text-neutral-600">
                      {new Date(d.ts).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-neutral-400">{d.reason}</div>
                  {(d.kind === "ENTRY" || (d.kind === "MANUAL" && d.action === "BUY")) && (
                    <EntryDetail detail={d.detail} />
                  )}
                  {(d.kind === "EXIT" || d.action === "SELL") && d.detail?.pnl !== undefined && (
                    <div className="mt-1 text-[11px] text-neutral-500">
                      P&L{" "}
                      <span className={pnlColor(Number(d.detail?.pnl ?? 0))}>
                        {formatCurrency(Number(d.detail?.pnl ?? 0))} (
                        {formatPercent(Number(d.detail?.pnl_pct ?? 0))})
                      </span>
                      {Number(d.detail?.cut_short_by ?? 0) > 0 && (
                        <span className="ml-2 text-amber-400">
                          cut {String(d.detail.cut_short_by)} days short of the exit rule
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EntryDetail({ detail }: { detail: Record<string, unknown> }) {
  const chips: [string, unknown][] = [
    ["RSI2", detail.rsi2],
    ["ATR%", detail.atr_pct],
    ["SMA50 buf", detail.sma50_buffer],
    ["52w dist", detail.high52_dist],
    ["WR", detail.backtest_wr],
    ["trades", detail.backtest_trades],
    ["analyst", detail.analyst_consensus],
    ["sentiment", detail.sentiment_label],
    ["exit", detail.exit_plan],
  ];
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {chips
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => (
          <span
            key={k}
            className="rounded bg-neutral-900 px-1.5 py-0.5 text-[10px] text-neutral-500"
          >
            {k} <span className="text-neutral-300">{typeof v === "number" ? v.toFixed(1) : String(v)}</span>
          </span>
        ))}
    </div>
  );
}

function StatRow({ label, s }: { label: string; s: SimTradeStats }) {
  return (
    <tr className="hover:bg-neutral-900/40">
      <td className="px-3 py-2 text-neutral-200">{label}</td>
      <td className="px-3 py-2 text-right tabular-nums text-neutral-400">{s.closed_trades}</td>
      <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
        {s.closed_trades ? `${s.win_rate.toFixed(0)}%` : "—"}
      </td>
      <td className={cn("px-3 py-2 text-right tabular-nums", pnlColor(s.avg_return_pct))}>
        {s.closed_trades ? formatPercent(s.avg_return_pct) : "—"}
      </td>
      <td className={cn("px-3 py-2 text-right tabular-nums", pnlColor(s.realized_pnl))}>
        {s.closed_trades ? formatCurrency(s.realized_pnl) : "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
        {s.profit_factor === null ? "—" : s.profit_factor.toFixed(2)}
      </td>
    </tr>
  );
}

function ClosedTable({
  history,
  strategies,
}: {
  history: SimHistoryResponse | null;
  strategies: SimStrategy[];
}) {
  if (!history || history.closed_positions.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
        No closed trades yet. The swing sleeve exits in days; the mean-reversion and breakout
        sleeves run 42 and 90 trading-day timers, so their first exits land later.
      </div>
    );
  }
  const s = history.stats;
  const label = (id: string) => strategies.find((x) => x.id === id)?.short ?? id;

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="bg-neutral-900/60 text-[11px] uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-3 py-2 text-left">Attribution</th>
              <th className="px-3 py-2 text-right">Trades</th>
              <th className="px-3 py-2 text-right">WR</th>
              <th className="px-3 py-2 text-right">Avg</th>
              <th className="px-3 py-2 text-right">Realized</th>
              <th className="px-3 py-2 text-right">PF</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            <StatRow label="All alpha trades" s={s} />
            {Object.entries(s.by_strategy).map(([sid, st]) => (
              <StatRow key={sid} label={`  ${label(sid)}`} s={st} />
            ))}
            {Object.entries(s.by_origin).map(([o, st]) => (
              <StatRow key={o} label={o === "MANUAL" ? "  ✋ Manual decisions" : "  🤖 Model decisions"} s={st} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="bg-neutral-900/60 text-[11px] uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-3 py-2 text-left">Ticker</th>
              <th className="px-3 py-2 text-left">Strategy</th>
              <th className="px-3 py-2 text-left">Entry</th>
              <th className="px-3 py-2 text-left">Exit</th>
              <th className="px-3 py-2 text-right">P&L</th>
              <th className="px-3 py-2 text-left">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {history.closed_positions.map((c) => {
              const pct = c.cost_basis ? (c.realized_pnl / c.cost_basis) * 100 : 0;
              return (
                <tr key={c.id} className="hover:bg-neutral-900/40">
                  <td className="px-3 py-2 font-medium text-neutral-100">
                    {c.ticker}
                    {c.origin === "MANUAL" && <span className="ml-1 text-[10px] text-cyan-400">✋</span>}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-400">{label(c.strategy)}</td>
                  <td className="px-3 py-2 text-xs text-neutral-400">
                    {c.entry_date} @ ${c.entry_price.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-400">
                    {c.exit_date} @ ${c.exit_price.toFixed(2)}
                  </td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", pnlColor(c.realized_pnl))}>
                    {formatCurrency(c.realized_pnl)}
                    <span className="ml-1 text-[11px]">({formatPercent(pct)})</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-500">{c.exit_reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PolicyPanel({ state, onSaved }: { state: SimState; onSaved: () => void }) {
  const [draft, setDraft] = useState(state.config);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const fields: { key: keyof typeof draft; label: string; hint: string; step?: number }[] = [
    { key: "core_target_pct", label: "Core target %", hint: `passive ${draft.core_ticker} weight`, step: 5 },
    { key: "core_band_pct", label: "Rebalance band ±pp", hint: "drift tolerated before trading", step: 1 },
    { key: "cycle_minutes", label: "Cycle every (min)", hint: "how often it decides in RTH", step: 15 },
    { key: "max_position_pct", label: "Max position %", hint: "hard cap of equity per name", step: 1 },
    { key: "min_composite", label: "Min composite", hint: "score floor for an entry", step: 5 },
    { key: "max_per_sector", label: "Max per sector", hint: "concentration guard", step: 1 },
    { key: "rotation_min_gap", label: "Auto-switch gap", hint: "score edge required to rotate", step: 5 },
    { key: "slippage_bps", label: "Slippage bps", hint: "adverse fill each way", step: 1 },
  ];

  const save = async () => {
    setSaving(true);
    try {
      await api.setSimConfig(draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-xs leading-relaxed text-neutral-400">
        <div className="mb-2 font-semibold text-neutral-200">How this book is run</div>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="text-neutral-300">Several strategies at once.</span> Each sleeve gets its
            own slots and its own exit rule; the Strategies tab shows what each one is and the
            evidence behind it. Tier A is walk-forward validated, B is study-supported, C is weak.
          </li>
          <li>
            <span className="text-neutral-300">Shared gates.</span> Every entry, whichever sleeve, must
            clear the regime gate, the Phase-3 validation filter, the veto chain (penny, ATR≥15%,
            analyst Hold/Sell, &lt;10 backtest trades, composite floor) and the sector cap.
          </li>
          <li>
            <span className="text-neutral-300">Exits.</span> Each sleeve exits on its own rule, plus two
            universal ones: earnings within 7 days, and stock-specific bad news. No stops, no
            targets — every stop variant tested lost to letting the rule run.
          </li>
          <li>
            <span className="text-neutral-300">Auto-switching is off.</span> Composite rotation tested
            13–24 CAGR points below simply holding. Manual switches stay available and are tracked
            separately so their cost is measurable rather than assumed.
          </li>
        </ul>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {fields.map((f) => (
          <label key={String(f.key)} className="flex flex-col gap-1">
            <span className="text-[11px] text-neutral-400">{f.label}</span>
            <input
              type="number"
              step={f.step ?? 1}
              value={Number(draft[f.key])}
              onChange={(e) => setDraft({ ...draft, [f.key]: Number(e.target.value) })}
              className="rounded-md border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-100 focus:border-neutral-500 focus:outline-none"
            />
            <span className="text-[10px] text-neutral-600">{f.hint}</span>
          </label>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Toggle
          label="Autonomous loop"
          on={!!draft.enabled}
          onChange={(v) => setDraft({ ...draft, enabled: v ? 1 : 0 })}
        />
        <Toggle
          label="Auto-switch (rotation)"
          on={!!draft.rotation_enabled}
          onChange={(v) => setDraft({ ...draft, rotation_enabled: v ? 1 : 0 })}
          warn
        />
        <button
          onClick={save}
          disabled={saving}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-signal-buy/20 px-4 py-2 text-xs font-medium text-signal-buy hover:bg-signal-buy/30 disabled:opacity-50"
        >
          {saved ? <Check className="h-3.5 w-3.5" /> : <RefreshCw className={cn("h-3.5 w-3.5", saving && "animate-spin")} />}
          {saved ? "Saved" : "Save policy"}
        </button>
      </div>
      {!!draft.rotation_enabled && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
          Auto-switch is ON. The engine will sell the weakest holding whenever a candidate beats it
          by {draft.rotation_min_gap} composite points. Our point-in-time test of this exact logic
          returned 13–24 CAGR points below holding to the timer.
        </div>
      )}
    </div>
  );
}

function Toggle({
  label,
  on,
  onChange,
  warn,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
  warn?: boolean;
}) {
  return (
    <button onClick={() => onChange(!on)} className="flex items-center gap-2 text-xs text-neutral-300">
      <span
        className={cn(
          "flex h-5 w-9 items-center rounded-full p-0.5 transition-colors",
          on ? (warn ? "bg-amber-500/60" : "bg-signal-buy/60") : "bg-neutral-700"
        )}
      >
        <span
          className={cn(
            "h-4 w-4 rounded-full bg-neutral-100 transition-transform",
            on && "translate-x-4"
          )}
        />
      </span>
      {label}
    </button>
  );
}
