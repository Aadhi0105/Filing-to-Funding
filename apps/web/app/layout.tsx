import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Company Explorer | Filing-to-Funding",
  description: "Historical liquidity and cash-flow research from qualified SEC filings.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
