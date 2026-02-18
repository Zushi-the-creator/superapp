import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number, showSign = true): string {
  const sign = showSign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatDateFull(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function pnlColor(value: number): string {
  if (value > 0) return "text-signal-buy";
  if (value < 0) return "text-signal-sell";
  return "text-neutral-400";
}

export function signalColor(signal: string): string {
  const s = signal.toUpperCase();
  if (s.includes("BUY") || s === "OPPORTUNITY") return "text-signal-buy";
  if (s.includes("SELL") || s === "CRASH" || s === "CRITICAL") return "text-signal-sell";
  if (s.includes("CAUTION") || s === "WARNING") return "text-amber-400";
  if (s === "ROTATION") return "text-orange-400";
  return "text-neutral-400";
}

export function isUSMarketOpen(): boolean {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  if (day === 0 || day === 6) return false; // Weekend
  const minutes = et.getHours() * 60 + et.getMinutes();
  return minutes >= 570 && minutes <= 960; // 9:30 AM - 4:00 PM ET
}

export function signalBg(signal: string): string {
  const s = signal.toUpperCase();
  if (s.includes("BUY")) return "bg-signal-buy/15 text-signal-buy border-signal-buy/30";
  if (s.includes("SELL") || s === "CRASH") return "bg-signal-sell/15 text-signal-sell border-signal-sell/30";
  if (s === "EXIT") return "bg-orange-500/15 text-orange-400 border-orange-500/30 animate-pulse";
  if (s.includes("CAUTION")) return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  if (s === "ROTATION") return "bg-orange-500/15 text-orange-400 border-orange-500/30";
  if (s === "OVERBOUGHT") return "bg-blue-500/15 text-blue-400 border-blue-500/30";
  return "bg-neutral-700/50 text-neutral-300 border-neutral-600/30";
}
