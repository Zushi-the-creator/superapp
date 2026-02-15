export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export const REFRESH_INTERVALS = {
  portfolio: 60_000,         // 60 seconds during market hours
  health: 900_000,           // 15 minutes during market hours
  scanner: 900_000,          // 15 minutes during market hours
  portfolioOffHours: 300_000, // 5 minutes outside market hours
  healthOffHours: 3_600_000,  // 1 hour outside market hours
  scannerOffHours: 300_000,   // 5 minutes outside market hours
} as const;

export const COLORS = {
  green: "#10b981",
  red: "#ef4444",
  amber: "#f59e0b",
  blue: "#3b82f6",
  gray: "#6b7280",
} as const;

export const REGIME_COLORS: Record<string, string> = {
  BULL: COLORS.green,
  SIDEWAYS: COLORS.amber,
  BEAR: COLORS.red,
};
