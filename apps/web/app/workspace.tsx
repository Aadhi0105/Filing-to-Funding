import Link from "next/link";
import type { ReactNode } from "react";
import { BarChart3, Database, FileText, GitCompareArrows, Landmark, LayoutDashboard, TrendingUp } from "lucide-react";

const links = [
  ["/overview", "Overview", LayoutDashboard],
  ["/", "Company Explorer", BarChart3],
  ["/peers", "Peer Comparison", GitCompareArrows],
  ["/funding", "Funding Scenarios", TrendingUp],
  ["/data-quality", "Data Quality & Filing History", FileText],
] as const;

export function Workspace({ children, route, version, query }: {
  children: ReactNode; route: string; version?: string; query?: string;
}) {
  return <div className="workspace">
    <a className="skip" href="#main-content">Skip to content</a>
    <aside className="sidebar" aria-label="Workspace navigation">
      <Link className="brand" href={`/overview${query || ""}`}>
        <span className="brand-mark"><Landmark size={21} aria-hidden="true" /></span>
        <span>Filing-to-Funding</span>
      </Link>
      <nav>{links.map(([href, name, Icon]) => <Link key={href}
        className={`nav-link${route === href ? " nav-current" : ""}`}
        href={`${href}${query || ""}`} aria-current={route === href ? "page" : undefined}>
        <Icon size={18} aria-hidden="true" />{name}
      </Link>)}</nav>
      <div className="sidebar-caption"><Database size={16} /><span>Local research workspace</span></div>
    </aside>
    <div className="right-pane">
      <header className="topbar">
        <span>Research workspace</span>
        <span className="dataset-badge"><i />{version ? `Dataset ${version}` : "Local dataset"}</span>
      </header>
      <main id="main-content" className="content">{children}</main>
    </div>
  </div>;
}
