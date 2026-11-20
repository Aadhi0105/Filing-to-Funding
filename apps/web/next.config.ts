import type { NextConfig } from "next";

const config: NextConfig = {
  devIndicators: false,
  async rewrites() {
    const origin = process.env.FILING_API_ORIGIN || "http://127.0.0.1:8000";
    return [{ source: "/api/v1/:path*", destination: `${origin}/api/v1/:path*` }];
  },
};
export default config;
