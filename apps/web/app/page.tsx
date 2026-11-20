"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle, BarChart3, Building2, CalendarDays, ChevronDown, Database,
  Download, ExternalLink, FileText, Landmark, Layers3,
} from "lucide-react";
import type { components } from "./api-types";
import { FlowChart, fiscalLabel } from "./flow-chart";
import { Button } from "../components/ui/button";

type Model = components["schemas"];
type Mode = Model["Context"]["mode"];
type Duration = Model["Analysis"]["duration"];
type Context = Model["Context"];
type Period = Model["Period"];
type Metric = Model["Metric"];
type Settings = { cik: string; mode: Mode; duration: Duration; filedBy: string; version: string; period: string };
type Result = {
  analysis?: Model["Analysis"];
  companies: Model["Company"][];
  periods: Period[];
  context: Context;
  exportUrl?: string;
};
const base = "/api/v1";
const defaultSettings: Settings = {
  cik: "0000049826", mode: "latest", duration: "quarter", filedBy: "", version: "", period: "",
};
const modes: [Mode, string][] = [
  ["latest", "Latest reported"], ["filed_by", "Filed by date"], ["platform_snapshot", "Platform snapshot"],
];
const durations: [Duration, string][] = [["quarter", "Quarter"], ["annual", "Annual"], ["ttm", "Trailing 12 months"]];
const keyMetrics = ["free_cash_flow", "operating_cash_flow", "fcf_margin", "current_ratio"];
const metricLabels: Record<string, string> = {
  operating_cash_flow: "Operating cash flow", cash_capex: "Cash capital expenditure", free_cash_flow: "Free cash flow",
  fcf_margin: "FCF margin", cash_conversion: "Cash conversion", current_ratio: "Current ratio", cash_ratio: "Cash ratio",
  working_capital: "Working capital", borrowing_debt: "Borrowing debt", net_borrowing_debt: "Net borrowing debt",
  cash_to_debt: "Cash to borrowing debt", debt_to_assets: "Borrowing debt to assets",
};
const scopeLabels: Record<string, string> = {
  historical_balance_sheet: "Reported balance sheet",
  itw_from_fifo_change: "Consolidated · FIFO basis",
  itw_before_fifo_change: "Consolidated · pre-FIFO basis",
  dov_2020_continuing_operations: "Continuing operations · FY2020",
  dov_including_esg: "Consolidated · including ESG",
  dov_excluding_esg: "Continuing operations · excluding ESG",
  rok_sensia_transition_year: "Consolidated · Sensia transition",
  rok_before_sensia_transition: "Consolidated · before Sensia transition",
};
const statusLabels: Record<string, string> = {
  available: "Available",
  unsupported_by_snapshot: "Unavailable in this snapshot",
  conflicting_observations: "Conflicting filing evidence",
  missing_compatible_operands: "Missing compatible inputs",
  missing_compatible_quarters: "Incomplete trailing window",
  missing_compatible_denominator: "Missing compatible denominator",
  unverified_borrowing_basis: "Borrowing basis unverified",
  mixed_filings: "Inputs from different filings",
  nonpositive_denominator: "Nonpositive denominator",
};
const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const fmtDate = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" });

function dateLabel(value?: string | null) {
  return value ? fmtDate.format(new Date(`${value.slice(0, 10)}T12:00:00Z`)) : "—";
}

function statusLabel(value: string) {
  return statusLabels[value] || value.replaceAll("_", " ");
}

function labelFor(metric: string) {
  return metricLabels[metric] || metric.replaceAll("_", " ");
}

function displayValue(value: string | null, unit: string, compact = false) {
  if (value === null) return "—";
  const amount = Number(value);
  if (unit === "USD") {
    if (compact && Math.abs(amount) >= 1e6) {
      const divisor = Math.abs(amount) >= 1e9 ? 1e9 : 1e6;
      return `${amount < 0 ? "−" : ""}$${fmt.format(Math.abs(amount) / divisor)}${divisor === 1e9 ? "B" : "M"}`;
    }
    const [whole, fractional] = value.split(".");
    return `${whole.startsWith("-") ? "−" : ""}$${BigInt(whole.replace("-", "")).toLocaleString("en-US")}${fractional && Number(fractional) ? `.${fractional}` : ""}`;
  }
  if (unit === "fraction") return `${fmt.format(amount * 100)}%`;
  return `${fmt.format(amount)}×`;
}

function periodKey(period: Period) {
  return `${period.fiscal_year}-${period.quarter || 0}`;
}

async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === "string" ? payload.detail : "The local data could not be loaded.");
  }
  return response.json();
}

function initialSettings() {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get("mode");
  const duration = params.get("duration");
  return {
    ...defaultSettings,
    cik: params.get("company") || defaultSettings.cik,
    mode: modes.find(([value]) => value === mode)?.[0] || defaultSettings.mode,
    duration: durations.find(([value]) => value === duration)?.[0] || defaultSettings.duration,
    filedBy: params.get("filed_by") || "",
    version: params.get("dataset_version") || "",
    period: params.get("period") || "",
  };
}

function viewParams(settings: Settings, catalog: Model["DatasetList"]) {
  const active = catalog.versions.find(({ version }) => version === catalog.active_version);
  const result = new URLSearchParams({ mode: settings.mode });
  if (settings.mode === "filed_by") result.set("filed_by", settings.filedBy || active?.filing_cutoff || "");
  if (settings.mode === "platform_snapshot") result.set("dataset_version", settings.version || catalog.active_version);
  return result;
}

export default function Explorer() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [catalog, setCatalog] = useState<Model["DatasetList"]>();
  const [result, setResult] = useState<Result>();
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, retry] = useState(0);
  const [evidenceMetric, setEvidenceMetric] = useState("free_cash_flow");

  useEffect(() => { setSettings(initialSettings()); }, []);
  useEffect(() => {
    const abort = new AbortController();
    request<Model["DatasetList"]>(`${base}/datasets`, abort.signal).then(setCatalog).catch((error: Error) => {
      if (!abort.signal.aborted) { setMessage(error.message); setLoading(false); }
    });
    return () => abort.abort();
  }, [attempt]);

  useEffect(() => {
    if (!settings || !catalog) return;
    const selected = settings;
    const published = catalog;
    const abort = new AbortController();
    const signal = abort.signal;
    async function update() {
      setLoading(true);
      setMessage("");
      try {
        const params = viewParams(selected, published);
        const available = await request<Model["CompanyList"]>(`${base}/companies?${params}`, signal);
        const companies = available.companies;
        const issuer = companies.find(({ cik }) => cik === selected.cik) || companies[0];
        if (!issuer) {
          setResult({ context: available.context, companies, periods: [] });
          return;
        }
        params.set("duration", selected.duration);
        const share = new URLSearchParams(params);
        params.set("expected_dataset_version", available.context.dataset_version);
        const path = `${base}/companies/${issuer.cik}`;
        const { periods } = await request<Model["PeriodList"]>(`${path}/periods?${params}`, signal);
        const period = periods.find((item) => periodKey(item) === selected.period) || periods[0];
        if (!period) {
          setResult({ context: available.context, companies, periods });
          return;
        }
        share.set("company", issuer.cik);
        share.set("period", periodKey(period));
        params.set("fiscal_year", String(period.fiscal_year));
        if (period.quarter) params.set("quarter", String(period.quarter));
        const analysis = await request<Model["Analysis"]>(`${path}/analysis?${params}`, signal);
        if (signal.aborted) return;
        setResult({ context: analysis.context, companies, periods, analysis, exportUrl: `${path}/export.csv?${params}` });
        window.history.replaceState(null, "", `?${share}`);
      } catch (error) {
        if (!signal.aborted) {
          setResult(undefined);
          setMessage(error instanceof Error ? error.message : "The local data could not be loaded.");
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    }
    void update();
    return () => abort.abort();
  }, [settings, catalog, attempt]);

  const controls = settings || defaultSettings;
  const active = catalog?.versions.find(({ version }) => version === catalog.active_version);
  const analysis = loading ? undefined : result?.analysis;
  const primary = analysis?.metrics.find(({ metric }) => metric === evidenceMetric);
  const evidence = analysis?.sources.filter(({ fact_id }) => primary?.fact_ids.includes(fact_id)) || [];
  const quote = analysis?.metrics.find(({ metric }) => metric === "free_cash_flow");
  const company = analysis?.company;
  function change(update: Partial<Settings>) {
    setLoading(true);
    setSettings((current) => ({
      ...(current || defaultSettings),
      cik: result?.analysis?.company.cik || (current || defaultSettings).cik,
      period: result?.analysis ? periodKey(result.analysis.period) : (current || defaultSettings).period,
      ...update,
    }));
  }

  return (
    <div className="workspace">
      <a className="skip" href="#main-content">Skip to content</a>
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="#main-content">
          <span className="brand-mark"><Landmark size={21} aria-hidden="true" /></span>
          <span>Filing-to-Funding</span>
        </a>
        <nav>
          <a className="nav-link nav-current" href="#main-content" aria-current="page"><BarChart3 size={18} />Company Explorer</a>
          <a className="nav-link" href="#filing-evidence"><FileText size={18} />Filing evidence</a>
        </nav>
        <div className="sidebar-caption"><Database size={16} /><span>Local research workspace</span></div>
      </aside>
      <div className="right-pane">
        <header className="topbar">
          <span>Research workspace</span>
          <span className="dataset-badge"><i />{active ? `Active dataset ${active.version}` : "Local dataset"}</span>
        </header>
        <main id="main-content" className="content">
          <header className="page-heading">
            <div><h1>Company Explorer</h1><p>Liquidity and cash flow from qualified SEC filings.</p></div>
            {result?.exportUrl && !loading && <Button asChild><a href={result.exportUrl}><Download size={16} /> Export CSV</a></Button>}
          </header>

          <section className="panel controls" aria-label="Explorer filters">
            <div className="controls-row">
              <div className="field">
                <label htmlFor="company">Company</label>
                <div className="select-wrap"><select id="company" value={result?.analysis?.company.cik || controls.cik}
                  onChange={(event) => change({ cik: event.target.value, period: "" })}>
                  {(result?.companies || []).map(({ cik, ticker, name }) =>
                    <option key={cik} value={cik}>{ticker} — {name}</option>)}
                </select><ChevronDown size={16} /></div>
              </div>
              <div className="field mode-field">
                <label id="view-label">Reporting view</label>
                <div className="segmented" role="group" aria-labelledby="view-label">
                  {modes.map(([value, name]) => <button type="button" key={value} aria-pressed={controls.mode === value}
                    onClick={() => change({ mode: value })}>{name}</button>)}
                </div>
              </div>
              {controls.mode === "filed_by" && <div className="field">
                <label htmlFor="filed-by">Filed by date</label>
                <input type="date" id="filed-by" value={controls.filedBy || active?.filing_cutoff || ""}
                  max={active?.filing_cutoff} onChange={(event) => change({ filedBy: event.target.value })} />
              </div>}
              {controls.mode === "platform_snapshot" && <div className="field">
                <label htmlFor="snapshot">Snapshot version</label>
                <div className="select-wrap"><select id="snapshot" value={controls.version || catalog?.active_version || ""}
                  onChange={(event) => change({ version: event.target.value })}>
                  {catalog?.versions.slice().reverse().map(({ version }) =>
                    <option key={version} value={version}>{version}{version === catalog.active_version ? " (active)" : ""}</option>)}
                </select><ChevronDown size={16} /></div>
              </div>}
            </div>
            <div className="controls-row period-row">
              <div className="field">
                <label id="duration-label">Period type</label>
                <div className="segmented" role="group" aria-labelledby="duration-label">
                  {durations.map(([value, name]) => <button type="button" key={value} aria-pressed={controls.duration === value}
                    onClick={() => change({ duration: value, period: "" })}>{name}</button>)}
                </div>
              </div>
              <div className="field">
                <label htmlFor="period">Fiscal period</label>
                <div className="select-wrap"><select id="period" value={result?.analysis ? periodKey(result.analysis.period) : ""}
                  onChange={(event) => change({ period: event.target.value })}>
                  {result?.periods.map((item) => <option key={periodKey(item)} value={periodKey(item)}>
                    {fiscalLabel(item.fiscal_year, item.quarter)} · {dateLabel(item.period_end)}
                  </option>)}
                </select><ChevronDown size={16} /></div>
              </div>
            </div>
          </section>

          {loading && <div className="panel notice" role="status">Loading the selected filing data…</div>}
          {message && !loading && <div className="panel notice error" role="alert"><AlertCircle size={20} />
            <div>{message}</div><Button onClick={() => { setLoading(true); retry((value) => value + 1); }}>Retry</Button></div>}
          {!message && !loading && !analysis && <div className="panel notice" role="status">No fiscal periods are available at this cutoff.</div>}

          {analysis && company && <>
            <section className="issuer" aria-label="Selected company">
              <span className="issuer-icon"><Building2 size={24} /></span>
              <div><div className="issuer-title"><h2>{company.name}</h2><span className="ticker">{company.ticker}</span></div>
                <p><CalendarDays size={15} />{fiscalLabel(analysis.period.fiscal_year, analysis.period.quarter)}
                  <span>·</span> Ends {dateLabel(analysis.period.period_end)}</p>
              </div>
              <div className="issuer-context"><Layers3 size={16} /><div>
                <strong>{modes.find(([value]) => value === analysis.context.mode)?.[1]}</strong>
                <span>{analysis.context.filed_by ? `Through ${dateLabel(analysis.context.filed_by)} · New York` :
                  `Dataset ${analysis.context.dataset_version} · through ${dateLabel(analysis.context.filing_cutoff)}`}</span>
              </div></div>
            </section>

            <div className="metric-grid" aria-label="Key metrics">
              {keyMetrics.map((name) => {
                const metric = analysis.metrics.find((item) => item.metric === name);
                return metric && <button type="button" className="panel metric-card" key={name}
                  onClick={() => { setEvidenceMetric(name); document.getElementById("filing-evidence")?.scrollIntoView({ block: "nearest" }); }}>
                  <span>{labelFor(name)}</span>
                  <strong>{displayValue(metric.value, metric.unit, true)}</strong>
                  <small>{metric.status === "available" ? scopeLabels[metric.scope_key] || metric.reporting_basis : statusLabel(metric.status)}</small>
                </button>;
              })}
            </div>

            <section className="panel chart-panel" aria-labelledby="chart-heading">
              <div className="panel-heading"><div><h2 id="chart-heading">Free cash flow history</h2>
                <p>{durations.find(([value]) => value === analysis.duration)?.[1]} · USD millions</p></div>
                <span className="chart-badge">{analysis.context.dataset_version}</span></div>
              <FlowChart points={analysis.series} />
              <details className="chart-details">
                <summary>View chart data</summary>
                <div className="table-wrap"><table><thead><tr><th scope="col">Fiscal period</th><th scope="col">End date</th>
                  <th scope="col">Reporting scope</th><th scope="col">Free cash flow</th><th scope="col">Status</th></tr></thead>
                  <tbody>{analysis.series.map((point) => <tr key={periodKey(point)} data-testid="chart-data-row">
                    <th scope="row">{fiscalLabel(point.fiscal_year, point.quarter)}</th><td>{dateLabel(point.period_end)}</td>
                    <td>{scopeLabels[point.scope_key] || point.scope_key}</td>
                    <td data-value={point.value ?? ""}>{displayValue(point.value, "USD")}</td><td>{statusLabel(point.status)}</td>
                  </tr>)}</tbody></table></div>
              </details>
            </section>

            <div className="details-grid">
              <section className="panel data-panel" aria-labelledby="metrics-heading">
                <div className="panel-heading"><div><h2 id="metrics-heading">Period metrics</h2>
                  <p>Select a metric to inspect its filing evidence.</p></div></div>
                <div className="table-wrap"><table><thead><tr><th scope="col">Metric</th><th scope="col">Value</th><th scope="col">Status</th></tr></thead>
                  <tbody>{analysis.metrics.map((metric: Metric) => <tr key={metric.metric} data-testid="metric-row">
                    <th scope="row"><button type="button" className="text-button" aria-pressed={evidenceMetric === metric.metric}
                      onClick={() => setEvidenceMetric(metric.metric)}>{labelFor(metric.metric)}</button></th>
                    <td data-value={metric.value ?? ""}>{displayValue(metric.value, metric.unit)}</td><td>{statusLabel(metric.status)}</td>
                  </tr>)}</tbody></table></div>
              </section>
              <section id="filing-evidence" className="panel data-panel sources" aria-labelledby="evidence-heading">
                <div className="panel-heading"><div><h2 id="evidence-heading">Filing evidence</h2>
                  <p>{labelFor(evidenceMetric)} · {analysis.context.dataset_version}</p></div><FileText size={19} /></div>
                <div className="evidence-body">
                  {!evidence.length && <p>{statusLabel(primary?.status || quote?.status || "No filing evidence for this selection")}</p>}
                  {evidence.map((fact) => <article key={fact.fact_id} className="fact">
                    <div><strong>{labelFor(fact.concept)}</strong><span>{displayValue(fact.value, fact.unit, true)}</span></div>
                    <p>Filed {dateLabel(fact.filed_on)} · period ends {dateLabel(fact.period_end)}</p>
                    <a href={fact.filing_url} target="_blank" rel="noreferrer">{fact.accession}<ExternalLink size={13} /></a>
                    <details><summary>Source details</summary><p className="filename">{fact.source_locator}</p>
                      <p>Reported precision {fact.reported_decimals ?? "unavailable"}</p></details>
                  </article>)}
                </div>
              </section>
            </div>

            <section className="panel revisions" aria-labelledby="revision-heading">
              <div className="panel-heading"><div><h2 id="revision-heading">Filing revisions</h2>
                <p>{analysis.revisions.length ? "Original and later evidence for the selected period." :
                  catalog?.versions.find(({ version }) => version === analysis.context.dataset_version)?.annual_and_revisions === false ?
                    "Revision history is unavailable in this snapshot." : "No linked revisions for this period and view."}</p></div></div>
              {analysis.revisions.length > 0 && <div className="table-wrap"><table><thead><tr>
                <th scope="col">Measure and relationship</th><th scope="col">Earlier filing</th><th scope="col">Later filing</th></tr></thead>
                <tbody>{analysis.revisions.map((entry, index) => <tr key={`${entry.concept}-${entry.prior_accession}-${entry.later_accession}-${index}`}>
                  <th scope="row">{labelFor(entry.concept)}<small>{statusLabel(entry.relationship)}</small></th>
                  <td><a href={entry.prior_url} target="_blank" rel="noreferrer">{entry.prior_accession}</a>
                    <small>{displayValue(entry.prior_value, entry.unit, true)} · {dateLabel(entry.prior_filed_on)}</small></td>
                  <td><a href={entry.later_url} target="_blank" rel="noreferrer">{entry.later_accession}</a>
                    <small>{displayValue(entry.later_value, entry.unit, true)} · {dateLabel(entry.later_filed_on)}</small></td>
                </tr>)}</tbody></table></div>}
            </section>
          </>}
        </main>
      </div>
    </div>
  );
}
