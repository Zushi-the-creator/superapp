"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import type { PositionDetail } from "@/lib/types";

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

export function AllocationChart({
  positions,
}: {
  positions: PositionDetail[];
}) {
  if (!positions.length) return null;

  const data = positions.map((p, i) => ({
    name: p.ticker,
    value: p.current_value,
    weight: p.weight,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
      <h3 className="text-xs text-neutral-500 mb-3 font-medium">Allocation</h3>
      <div className="flex items-center gap-4">
        <div className="w-28 h-28">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={30}
                outerRadius={50}
                dataKey="value"
                stroke="none"
              >
                {data.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "#262626",
                  border: "1px solid #404040",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                formatter={(value: number) =>
                  `$${value.toFixed(0)} (${((value / data.reduce((s, d) => s + d.value, 0)) * 100).toFixed(1)}%)`
                }
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-1.5">
          {data.map((d) => (
            <div key={d.name} className="flex items-center gap-2 text-xs">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: d.color }}
              />
              <span className="text-neutral-300 font-medium">{d.name}</span>
              <span className="text-neutral-500">{d.weight.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
