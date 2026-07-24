"use client";

import { useMemo } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip,
  ReferenceLine, ReferenceArea, ResponsiveContainer,
} from "recharts";
import type { SectorData } from "@/lib/types";
import { QUADRANT_COLORS } from "./quadrant";

interface TrailPoint {
  date: string;
  rs_ratio: number;
  rs_momentum: number;
  name: string;
  etf: string;
  isHead: boolean;
}

function TrailDot(props: any) {
  const { cx, cy, payload, dimmed } = props;
  if (cx == null || cy == null) return null;
  const color = props.fill as string;
  const opacity = dimmed ? 0.25 : 1;
  if (payload.isHead) {
    return (
      <g opacity={opacity}>
        <circle cx={cx} cy={cy} r={6} fill={color} stroke="#171717" strokeWidth={1.5} />
        <text x={cx + 9} y={cy + 4} fontSize={11} fontWeight={700} fill={color}>
          {payload.etf}
        </text>
      </g>
    );
  }
  return <circle cx={cx} cy={cy} r={2.5} fill={color} opacity={dimmed ? 0.15 : 0.55} />;
}

function RRGTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p: TrailPoint = payload[0].payload;
  return (
    <div className="rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold text-neutral-200">{p.name} ({p.etf})</div>
      <div className="text-neutral-500">{p.date}</div>
      <div className="text-neutral-300 mt-1">
        RS-Ratio {p.rs_ratio.toFixed(1)} · RS-Momentum {p.rs_momentum.toFixed(1)}
      </div>
    </div>
  );
}

export function RRGQuadrantChart({
  sectors,
  selectedEtf,
  onSelect,
}: {
  sectors: SectorData[];
  selectedEtf: string | null;
  onSelect: (etf: string | null) => void;
}) {
  const withTrails = useMemo(
    () => sectors.filter((s) => s.trail && s.trail.length > 0),
    [sectors]
  );

  const domain = useMemo(() => {
    const xs: number[] = [100];
    const ys: number[] = [100];
    withTrails.forEach((s) =>
      s.trail.forEach((p) => {
        xs.push(p.rs_ratio);
        ys.push(p.rs_momentum);
      })
    );
    const pad = 1;
    return {
      x: [Math.floor(Math.min(...xs)) - pad, Math.ceil(Math.max(...xs)) + pad] as [number, number],
      y: [Math.floor(Math.min(...ys)) - pad, Math.ceil(Math.max(...ys)) + pad] as [number, number],
    };
  }, [withTrails]);

  if (withTrails.length === 0) {
    return (
      <div className="flex h-[420px] items-center justify-center text-xs text-neutral-500">
        Not enough history for rotation analysis
      </div>
    );
  }

  return (
    <div className="h-[420px]">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 10, right: 40, bottom: 10, left: 0 }}>
          {/* Quadrant tints */}
          <ReferenceArea x1={100} x2={domain.x[1]} y1={100} y2={domain.y[1]} fill={QUADRANT_COLORS.Leading} fillOpacity={0.06}
            label={{ value: "LEADING", position: "insideTopRight", fontSize: 10, fill: QUADRANT_COLORS.Leading, fontWeight: 700 }} />
          <ReferenceArea x1={100} x2={domain.x[1]} y1={domain.y[0]} y2={100} fill={QUADRANT_COLORS.Weakening} fillOpacity={0.06}
            label={{ value: "WEAKENING", position: "insideBottomRight", fontSize: 10, fill: QUADRANT_COLORS.Weakening, fontWeight: 700 }} />
          <ReferenceArea x1={domain.x[0]} x2={100} y1={domain.y[0]} y2={100} fill={QUADRANT_COLORS.Lagging} fillOpacity={0.06}
            label={{ value: "LAGGING", position: "insideBottomLeft", fontSize: 10, fill: QUADRANT_COLORS.Lagging, fontWeight: 700 }} />
          <ReferenceArea x1={domain.x[0]} x2={100} y1={100} y2={domain.y[1]} fill={QUADRANT_COLORS.Improving} fillOpacity={0.06}
            label={{ value: "IMPROVING", position: "insideTopLeft", fontSize: 10, fill: QUADRANT_COLORS.Improving, fontWeight: 700 }} />

          <XAxis
            type="number" dataKey="rs_ratio" domain={domain.x}
            tick={{ fontSize: 10, fill: "#737373" }} tickCount={7}
            label={{ value: "RS-Ratio (vs SPY)", position: "insideBottom", offset: -5, fontSize: 10, fill: "#737373" }}
            stroke="#404040"
          />
          <YAxis
            type="number" dataKey="rs_momentum" domain={domain.y}
            tick={{ fontSize: 10, fill: "#737373" }} tickCount={7}
            label={{ value: "RS-Momentum", angle: -90, position: "insideLeft", fontSize: 10, fill: "#737373" }}
            stroke="#404040"
          />
          <ReferenceLine x={100} stroke="#525252" strokeWidth={1} />
          <ReferenceLine y={100} stroke="#525252" strokeWidth={1} />
          <Tooltip content={<RRGTooltip />} cursor={{ strokeDasharray: "3 3", stroke: "#525252" }} />

          {withTrails.map((s) => {
            const color = QUADRANT_COLORS[s.quadrant] ?? QUADRANT_COLORS.Unknown;
            const dimmed = selectedEtf !== null && selectedEtf !== s.etf;
            const data: TrailPoint[] = s.trail.map((p, i) => ({
              ...p, name: s.name, etf: s.etf, isHead: i === s.trail.length - 1,
            }));
            return (
              <Scatter
                key={s.etf}
                data={data}
                fill={color}
                line={{ stroke: color, strokeWidth: 1.5, strokeOpacity: dimmed ? 0.15 : 0.5 }}
                shape={<TrailDot dimmed={dimmed} />}
                onClick={() => onSelect(selectedEtf === s.etf ? null : s.etf)}
                className="cursor-pointer"
                isAnimationActive={false}
              />
            );
          })}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
