"use client";

export function ScoreGauge({
  value,
  size = 60,
}: {
  value: number;
  size?: number;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - 8) / 2;
  const circumference = Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  let color = "#ef4444"; // red < 55
  if (clamped >= 70) color = "#10b981"; // green
  else if (clamped >= 55) color = "#f59e0b"; // amber

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size / 2 + 12 }}>
      <svg width={size} height={size / 2 + 4} viewBox={`0 0 ${size} ${size / 2 + 4}`}>
        {/* Background arc */}
        <path
          d={`M 4 ${size / 2} A ${radius} ${radius} 0 0 1 ${size - 4} ${size / 2}`}
          fill="none"
          stroke="#404040"
          strokeWidth={4}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <path
          d={`M 4 ${size / 2} A ${radius} ${radius} 0 0 1 ${size - 4} ${size / 2}`}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <span
        className="absolute text-xs font-bold"
        style={{ color, bottom: 0 }}
      >
        {clamped.toFixed(0)}%
      </span>
    </div>
  );
}
