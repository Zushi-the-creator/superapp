"use client";

export function LivePulse({ positive }: { positive: boolean }) {
  const color = positive ? "bg-signal-buy" : "bg-signal-sell";
  return (
    <span className="relative flex h-2 w-2">
      <span
        className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-75`}
      />
      <span
        className={`relative inline-flex rounded-full h-2 w-2 ${color}`}
      />
    </span>
  );
}
