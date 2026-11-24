import type { NextConfig } from "next";

const development = process.env.NODE_ENV === "development";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  `connect-src 'self'${development ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const config: NextConfig = {
  devIndicators: false,
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: contentSecurityPolicy },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
  async rewrites() {
    const configured = process.env.FILING_API_ORIGIN;
    let origin: URL;
    try {
      origin = new URL(configured || "http://127.0.0.1:8000");
    } catch {
      throw new Error("FILING_API_ORIGIN is invalid.");
    }
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password ||
        origin.pathname !== "/" || origin.search || origin.hash) {
      throw new Error("FILING_API_ORIGIN must be an HTTP or HTTPS origin without credentials, parameters, or a path.");
    }
    if (process.env.VERCEL_ENV === "production" && (!configured || origin.protocol !== "https:" ||
        !process.env.FILING_GCP_WIF_PROVIDER || !process.env.FILING_GCP_INVOKER_ACCOUNT)) {
      throw new Error("Configure the private HTTPS origin and its Google Cloud identity before a production build.");
    }
    if (process.env.FILING_GCP_WIF_PROVIDER) return [];
    return { beforeFiles: [{ source: "/api/v1/:path*", destination: `${origin.origin}/api/v1/:path*` }] };
  },
};
export default config;
