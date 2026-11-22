import Link from "next/link";
import type { ReactNode } from "react";
import { AlertCircle, BarChart3, Database, FileText, GitCompareArrows, Landmark, LayoutDashboard, TrendingUp } from "lucide-react";
import type { components } from "./api-types";

const links = [
  ["/overview", "Overview", LayoutDashboard],
  ["/", "Company Explorer", BarChart3],
  ["/peers", "Peer Comparison", GitCompareArrows],
  ["/funding", "Funding Scenarios", TrendingUp],
  ["/data-quality", "Data Quality & Filing History", FileText],
] as const;

const dateLabel = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" });

export function Workspace({ children, route, version, query, catalog }: {
  children: ReactNode; route: string; version?: string; query?: string; catalog?: components["schemas"]["DatasetList"] | null;
}) {
  const active = catalog?.versions.find((entry) => entry.version === catalog.active_version);
  const archived = Boolean(version && active && version !== active.version);
  const refresh = catalog?.refresh;
  const notices = [];
  if (refresh?.publication_status === "failed") notices.push("The last publication attempt failed.");
  if (refresh?.source_status === "failed") notices.push("The last source check failed.");
  if (refresh?.source_status === "review_required") notices.push("New source data is awaiting review.");
  if (refresh?.source_status === "overdue" || refresh?.source_check_overdue) {
    notices.push("The next source check is overdue.");
  }
  if (refresh?.source_status === "unknown") notices.push("Source check status is unavailable.");
  if (active && refresh?.filing_coverage_stale) {
    notices.push(`SEC coverage ends ${dateLabel.format(new Date(active.filing_cutoff))}.`);
  }
  if (active && refresh?.treasury_coverage_stale) {
    notices.push(`Treasury coverage ends ${dateLabel.format(new Date(active.treasury_end))}.`);
  }
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
        <span className="dataset-badge"><i />{archived ? `Archived dataset ${version}` : version ? `Dataset ${version}` : "Local dataset"}</span>
      </header>
      <main id="main-content" className="content">
        <div role="status">
          {active && !archived && notices.length > 0 && <p className="refresh-notice">
            <AlertCircle size={18} aria-hidden="true" />
            <span><strong>Showing verified dataset {active.version}.</strong> {notices.join(" ")}</span>
          </p>}
        </div>
        {children}
      </main>
    </div>
  </div>;
}
