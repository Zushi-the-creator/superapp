import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  async rewrites() {
    // Only proxy in dev — in production, vercel.json rewrites handle this
    if (process.env.NODE_ENV === "production") return [];
    const dest = process.env.API_PROXY || "http://localhost:8000/api/:path*";
    return [
      {
        source: "/api/:path*",
        destination: dest,
      },
    ];
  },
};

export default nextConfig;
