"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Download, ExternalLink } from "lucide-react";
import { Button } from "../components/ui/button";
import type { components } from "./api-types";
import { Workspace } from "./workspace";

type Model = components["schemas"];
type Mode = Model["Context"]["mode"];
type Duration = Model["PeerComparison"]["duration"];
type Page = "overview" | "peers" | "funding" | "data-quality";
type Metric = Model["Metric"];
type Filters = { mode: Mode; date: string; version: string };

const views = {
  overview: ["Overview", "Compare each company’s latest eligible fiscal quarter and open its filing evidence."],
  peers: ["Peer Comparison", "Compare industrial issuers on aligned periods and a consolidated reporting basis."],
  funding: ["Funding Scenarios", "Estimate the interest impact of a rate shock on USD debt that reprices."],
  "data-quality": ["Data Quality & Filing History", "Check EDGAR acceptance dates and which filings supply qualified facts."],
};
const modes: Record<Mode, string> = {
  latest: "Latest reported", filed_by: "Filed by date", platform_snapshot: "Platform snapshot",
};
const maturities = { two_year: "2-year", five_year: "5-year", ten_year: "10-year" };
const metrics = {
  free_cash_flow: "Free cash flow", working_capital: "Working capital", current_ratio: "Current ratio",
};
const statusLabels: Record<string, string> = {
  different_period_end: "Different period end", different_period_start: "Different window start",
  different_reporting_basis: "Different reporting basis", no_eligible_filing: "No eligible filing",
  observed_on_cutoff: "Observed on requested date", carried_forward: "Carried forward from last observation",
  missing_observation: "No earlier observation", historical_vintage_unverified: "Historical publication vintage unverified",
  available: "Available", structural_transition: "Sensia reporting transition",
  missing_compatible_inputs: "Missing compatible inputs", no_qualified_observations: "No qualified observations",
};
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 1, notation: "compact" });
const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const date = (value: string) => new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium", timeZone: "UTC",
}).format(new Date(value));
const accepted = (value: string) => new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium", timeStyle: "short", timeZone: "America/New_York",
}).format(new Date(value));
const label = (status: string) => statusLabels[status] || status.replaceAll("_", " ");
const amount = (metric?: Metric | null) => metric?.value == null
  ? "Unavailable" : metric.unit === "x" ? `${Number(metric.value).toFixed(2)}×` : usd.format(Number(metric.value));

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}

function useResource<T>(path: string | null) {
  const [state, setState] = useState<{ path: string; value?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    request<T>(path, { signal: controller.signal })
      .then((value) => setState({ path, value }))
      .catch((error: Error) => { if (!controller.signal.aborted) setState({ path, error: error.message }); });
    return () => controller.abort();
  }, [path]);
  const current = state?.path === path ? state : undefined;
  return { value: current?.value, error: current?.error, pending: Boolean(path && !current) };
}

function reportingQuery(filters: Filters, version?: string) {
  const query = new URLSearchParams();
  if (filters.mode === "filed_by") {
    query.set("mode", filters.mode);
    query.set("filed_by", filters.date);
  }
  if (filters.mode === "platform_snapshot") {
    query.set("mode", filters.mode);
    query.set("dataset_version", filters.version);
  }
  if (version) query.set("expected_dataset_version", version);
  return query;
}

function explorerLink(cik: string, period: Model["Period"], duration: Duration, filters: Filters) {
  const query = reportingQuery(filters);
  query.set("company", cik);
  query.set("duration", duration);
  query.set("period", `${period.fiscal_year}-${period.quarter || 0}`);
  return `/?${query}`;
}

function replaceParameters(values: Record<string, string>) {
  const query = new URLSearchParams(window.location.search);
  for (const [name, value] of Object.entries(values)) {
    if (value) query.set(name, value);
    else query.delete(name);
  }
  window.history.replaceState(null, "", query.size ? `?${query}` : window.location.pathname);
}

type CsvValue = string | number | null | undefined;
function downloadCsv(name: string, context: Model["Context"], fields: string[], rows: CsvValue[][]) {
  const details = [context.dataset_version, context.methodology_version, context.mode, context.filed_by, context.filing_cutoff];
  const encode = (value: CsvValue) => {
    const text = String(value ?? "");
    const formula = /^[\x00-\x20]*[=+@-]/.test(text) && !/^[+-]?\d+(?:\.\d+)?$/.test(text);
    return `"${(formula ? "'" + text : text).replaceAll('"', '""')}"`;
  };
  const header = [...fields, "dataset_version", "methodology_version", "mode", "filed_by", "filing_cutoff"];
  const csv = [header, ...rows.map((row) => [...row, ...details])].map((row) => row.map(encode).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv + "\r\n"], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name}-${context.dataset_version}.csv`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ExportButton({ action }: { action: () => void }) {
  return <Button type="button" variant="outline" onClick={action}><Download size={15} /> Export CSV</Button>;
}

function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={`panel notice${error ? " error" : ""}`} role={error ? "alert" : "status"}>{children}</div>;
}

function MetricCell({ metric }: { metric?: Metric }) {
  return <><strong>{amount(metric)}</strong>
    {metric?.value == null && metric && <small>{label(metric.status)}</small>}</>;
}

function Overview({ query, filters }: { query: string; filters: Filters }) {
  const resource = useResource<Model["Overview"]>(`/overview?${query}`);
  if (!resource.value) return <Notice error={!!resource.error}>{resource.error || "Loading company overview…"}</Notice>;
  if (resource.value.rows.length === 0) return <Notice>No companies are available at this cutoff.</Notice>;
  const result = resource.value;
  return <>
    <div className="research-toolbar"><p>Reported balance-sheet liquidity and cash-flow indicators.</p>
      <ExportButton action={() => downloadCsv("overview", result.context,
        ["ticker", "period_end", "metric", "unit", "value", "status", "basis", "accessions"],
        result.rows.flatMap((row) => Object.keys(metrics).map((name) => {
          const metric = row.metrics.find((entry) => entry.metric === name);
          return [row.company.ticker, row.period?.period_end, name, metric?.unit, metric?.value,
            metric?.status || "no_eligible_filing", metric?.reporting_basis, metric?.source_accessions.join("|")];
        })))} />
    </div>
    <div className="cohort-grid">
    {result.rows.map(({ company, period, note, metrics: values }) => <article className="panel cohort-card" key={company.cik}>
      <header>
        <span className="ticker">{company.ticker}</span>
        <h2>{company.name}</h2>
        <p>{period ? `FY${period.fiscal_year} Q${period.quarter} · ${date(period.period_end)}` : "No eligible fiscal quarter"}</p>
      </header>
      <dl>{Object.entries(metrics).map(([key, name]) => <div key={key}>
        <dt>{name}</dt><dd><MetricCell metric={values.find((entry) => entry.metric === key)} /></dd>
      </div>)}</dl>
      {note && <p className="filing-detail">{note}</p>}
      {period && <Link className="view-link" href={explorerLink(company.cik, period, "quarter", filters)}>
        Explore {company.ticker} <ArrowRight size={15} />
      </Link>}
    </article>)}
    </div>
    <p className="research-footnote">Undrawn credit, covenants, debt maturities, hedges, and cash restrictions are outside this assessment.</p>
  </>;
}

function Peers({ query, filters, limit }: { query: string; filters: Filters; limit: string }) {
  const saved = new URLSearchParams(window.location.search);
  const [duration, setDuration] = useState<Duration>(() => {
    const value = saved.get("duration");
    return value === "annual" || value === "ttm" ? value : "quarter";
  });
  const [metric, setMetric] = useState<keyof typeof metrics>(() => {
    const value = saved.get("metric");
    return value === "working_capital" || value === "current_ratio" ? value : "free_cash_flow";
  });
  const [end, setEnd] = useState(saved.get("period_end") || "");
  const parameters = new URLSearchParams(query);
  parameters.set("duration", duration);
  parameters.set("metric", metric);
  if (end) parameters.set("period_end", end);
  const resource = useResource<Model["PeerComparison"]>(`/peers?${parameters}`);
  const result = resource.value;
  return <>
    <section className="panel controls research-section" aria-label="Peer filters">
      <div className="controls-row">
        <div className="field"><label htmlFor="peer-metric">Metric</label><select id="peer-metric" value={metric}
          onChange={(event) => {
            setMetric(event.target.value as keyof typeof metrics);
            replaceParameters({ metric: event.target.value });
          }}>
          {Object.entries(metrics).map(([key, name]) => <option value={key} key={key}>{name}</option>)}
        </select></div>
        <div className="field"><label htmlFor="peer-duration">Period</label><select id="peer-duration" value={duration}
          onChange={(event) => {
            setDuration(event.target.value as Duration);
            setEnd("");
            replaceParameters({ duration: event.target.value, period_end: "" });
          }}>
          <option value="quarter">Quarter</option><option value="annual">Fiscal year</option>
          <option value="ttm">Trailing twelve months</option>
        </select></div>
        <div className="field"><label htmlFor="peer-end">Period end</label>
          <input id="peer-end" type="date" max={limit} value={end} onChange={(event) => { setEnd(event.target.value); replaceParameters({ period_end: event.target.value }); }} /></div>
      </div>
    </section>
    {!result ? <Notice error={!!resource.error}>{resource.error || "Loading peer comparison…"}</Notice> :
      <section className="panel research-section">
        <div className="panel-heading"><div><h2>{metrics[metric]}</h2>
          <p>Period ended {date(result.period_end)}. {!end && "Default uses the most common period end among the latest reports."}</p>
        </div><ExportButton action={() => downloadCsv("peer-comparison", result.context,
          ["ticker", "duration", "requested_period_end", "period_start", "period_end", "metric", "unit", "value", "status", "basis", "accessions"],
          result.rows.map((row) => [row.company.ticker, result.duration, result.period_end, row.window_start,
            row.period?.period_end, result.metric, row.metric?.unit, row.metric?.value, row.status,
            row.reporting_basis, row.metric?.source_accessions.join("|")]))} /></div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Peer comparison table"><table>
          <thead><tr><th>Company</th><th>Fiscal period</th><th>Window start</th><th>Window end</th><th>Reporting basis</th><th>Value</th><th>Evidence</th></tr></thead>
          <tbody>{result.rows.map((row) => <tr key={row.company.cik}>
            <th scope="row">{row.company.ticker}</th>
            <td>{row.period ? `FY${row.period.fiscal_year}${row.period.quarter ? ` Q${row.period.quarter}` : ""}` : "—"}</td>
            <td>{row.window_start ? date(row.window_start) : "—"}</td>
            <td>{row.period ? date(row.period.period_end) : "—"}</td>
            <td>{row.reporting_basis ? label(row.reporting_basis) : "—"}</td>
            <td>{row.metric?.value != null ? amount(row.metric) : <span className="filing-detail">{label(row.status)}</span>}</td>
            <td>{row.period && <Link href={explorerLink(row.company.cik, row.period, duration, filters)}>Explorer</Link>}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}
  </>;
}

function Funding({ query, limit }: { query: string; limit: string }) {
  const [curveDate, setCurveDate] = useState(() => new URLSearchParams(window.location.search).get("curve_date") || "");
  const parameters = new URLSearchParams(query);
  if (curveDate) parameters.set("curve_date", curveDate);
  const market = useResource<Model["MarketRates"]>(`/funding/curve?${parameters}`);
  const fields = [
    ["principal_usd", "Principal in USD", "100000000"], ["repricing_share", "Share repricing (0 to 1)", "0.25"],
    ["shock_bps", "Rate shock (bps)", "100"], ["horizon_years", "Horizon (years)", "1"],
  ];
  const [scenario, setScenario] = useState<Model["Scenario"]>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    setPending(true);
    setScenario(undefined);
    setError("");
    try {
      setScenario(await request<Model["Scenario"]>(`/funding/scenario?${query}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, spread_bps: data.spread_bps || null, curve_date: curveDate || null }),
      }));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Scenario unavailable.");
    } finally {
      setPending(false);
    }
  }
  const curve = market.value?.curve;
  return <div className="funding-grid">
    <section className="panel">
      <div className="panel-heading"><div><h2>Scenario inputs</h2><p>Enter the amount and terms you want to model.</p></div></div>
      <form className="scenario-form" onSubmit={run} onChange={() => { setScenario(undefined); setError(""); }}>
        <fieldset disabled={pending}>
          {fields.map(([key, name, value]) => <div className="field" key={key}><label htmlFor={key}>{name}</label>
            <input id={key} name={key} defaultValue={value} inputMode="decimal" required /></div>)}
          <div className="field"><label htmlFor="curve-date">Treasury reference date</label>
            <input type="date" id="curve-date" max={limit} value={curveDate}
              onChange={(event) => { setCurveDate(event.target.value); replaceParameters({ curve_date: event.target.value }); }} /></div>
          <div className="field"><label htmlFor="maturity">Treasury maturity</label><select id="maturity" name="maturity" defaultValue="five_year">
            {Object.entries(maturities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select></div>
          <div className="field"><label htmlFor="spread_bps">Spread (bps, optional)</label>
            <input id="spread_bps" name="spread_bps" inputMode="decimal" placeholder="For illustrative coupon" /></div>
        </fieldset>
        <Button type="submit" disabled={pending}>{pending ? "Calculating…" : "Calculate scenario"}</Button>
      </form>
    </section>
    <div>
      <section className="panel market-card">
        <div className="panel-heading"><div><h2>U.S. Treasury par yields</h2>
          <p>{curve ? `Requested ${date(curve.cutoff_date)}` : "Rates from the selected dataset"}</p>
        </div></div>
        {curve ? <div className="research-body">
          <dl className="rate-grid">
            {([["2-year", curve.two_year_percent], ["5-year", curve.five_year_percent],
              ["10-year", curve.ten_year_percent]] as const).map(([name, rate]) => <div key={name}><dt>{name}</dt>
              <dd>{rate == null ? "—" : `${Number(rate).toFixed(2)}%`}</dd></div>)}
          </dl>
          <p>{label(curve.status)}{curve.observation_date && ` · ${date(curve.observation_date)} · ${curve.observation_age_days} days old`}</p>
          {curve.ten_minus_two_bps != null && <p>10Y − 2Y spread {Number(curve.ten_minus_two_bps)} bps</p>}
          {curve.vintage_status && <p>{label(curve.vintage_status)}.</p>}
          {curve.source_retrieved_at && <p>Source retrieved {accepted(curve.source_retrieved_at)} ET</p>}
          {curve.source_url && <a className="view-link" href={curve.source_url} target="_blank" rel="noreferrer">Treasury source <ExternalLink size={14} /></a>}
        </div> : <p className="research-body" role={market.error ? "alert" : "status"}>{market.error || "Loading Treasury curve…"}</p>}
      </section>
      {error && <Notice error>{error}</Notice>}
      {scenario && <section className="panel research-section" aria-live="polite">
        <div className="panel-heading"><div><h2>Incremental interest</h2>
          <p className="scenario-value">{dollars.format(Number(scenario.incremental_interest_usd))}</p></div>
          <ExportButton action={() => downloadCsv("funding-scenario", scenario.context,
            ["currency", "scenario_methodology", "principal_usd", "repricing_share", "repricing_principal_usd",
              "horizon_years", "shock_bps", "incremental_interest_usd", "reference_maturity", "reference_yield_percent",
              "spread_bps", "baseline_coupon_percent", "shocked_coupon_percent", "baseline_interest_usd",
              "shocked_interest_usd", "curve_cutoff", "curve_observed", "curve_status", "curve_vintage", "curve_source"],
            scenario.sensitivity.map((point) => {
              const coupon = point.shock_bps === scenario.inputs.shock_bps ? scenario.illustrative_coupon : null;
              return [scenario.currency, scenario.methodology_version, scenario.inputs.principal_usd,
                scenario.inputs.repricing_share, scenario.repricing_principal_usd, scenario.inputs.horizon_years,
                point.shock_bps, point.incremental_interest_usd, scenario.reference_maturity,
                scenario.illustrative_coupon?.reference_yield_percent, scenario.illustrative_coupon?.spread_bps,
                coupon?.baseline_coupon_percent, coupon?.shocked_coupon_percent, coupon?.baseline_interest_usd,
                coupon?.shocked_interest_usd, scenario.curve?.cutoff_date, scenario.curve?.observation_date,
                scenario.curve?.status, scenario.curve?.vintage_status, scenario.curve?.source_url];
            }))} />
        </div>
        <div className="research-body">
          <p>Repricing principal {dollars.format(Number(scenario.repricing_principal_usd))}</p>
          {scenario.illustrative_coupon && <div>
            <p>Illustrative coupon {scenario.illustrative_coupon.baseline_coupon_percent}% → {scenario.illustrative_coupon.shocked_coupon_percent}%</p>
            {scenario.reference_maturity && <p>{maturities[scenario.reference_maturity]} Treasury reference {scenario.illustrative_coupon.reference_yield_percent}% with user spread {scenario.illustrative_coupon.spread_bps} bps</p>}
            <p>Interest {dollars.format(Number(scenario.illustrative_coupon.baseline_interest_usd))} → {dollars.format(Number(scenario.illustrative_coupon.shocked_interest_usd))}</p>
          </div>}
          {scenario.assumptions.map((assumption) => <p key={assumption}>{assumption}</p>)}
        </div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Funding sensitivity table"><table>
          <caption className="sr-only">Funding shock sensitivity</caption>
          <thead><tr><th>Annual shock (bps)</th><th>Incremental interest (USD)</th></tr></thead>
          <tbody>{scenario.sensitivity.map((point) => <tr key={point.shock_bps}>
            <th scope="row">{point.shock_bps}</th><td>{dollars.format(Number(point.incremental_interest_usd))}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}
    </div>
  </div>;
}

function Filings({ query, dataset }: { query: string; dataset: Model["DatasetRecord"] }) {
  const companies = useResource<Model["CompanyList"]>(`/companies?${query}`);
  const [cik, setCik] = useState(() => new URLSearchParams(window.location.search).get("cik") || "");
  const [page, setPage] = useState(1);
  const selected = companies.value?.companies.find((company) => company.cik === cik) || companies.value?.companies[0];
  const resource = useResource<Model["FilingHistory"]>(
    selected ? `/companies/${selected.cik}/filings?${query}&page=${page}` : null,
  );
  if (!companies.value) return <Notice error={!!companies.error}>{companies.error || "Loading companies…"}</Notice>;
  if (!selected) return <Notice>No companies are available at this cutoff.</Notice>;
  const result = resource.value;
  return <>
    <section className="panel">
      <div className="panel-heading"><div><h2>Published dataset</h2>
        <p>{dataset.row_counts.issuers} issuers · {dataset.row_counts.filings} SEC filings · {dataset.row_counts.qualified_statement_observations} qualified statement observations</p>
      </div></div>
      <div className="research-body">
        <p>Published {accepted(dataset.published_at)} ET. Each validation check listed below passed when the snapshot was published.</p>
        {dataset.row_counts.issuers > 3 && <p>AOS, IEX, and LECO have 27 verified filing records each. Statement coverage is limited to reviewed samples. A filing with zero qualified facts can still have verified metadata.</p>}
        <details><summary>Publication checks and methodology version</summary>
          <ul className="check-list">{dataset.validation_checks.map((check) => <li key={check}>{label(check)}</li>)}</ul>
          <p className="filename">Methodology {dataset.methodology_version}</p>
        </details>
      </div>
    </section>
    <section className="panel controls research-section" aria-label="Filing history filters">
      <div className="controls-row">
        <div className="field"><label htmlFor="filing-company">Company</label>
          <select id="filing-company" value={selected.cik} onChange={(event) => {
            setCik(event.target.value);
            setPage(1);
            replaceParameters({ cik: event.target.value });
          }}>
            {companies.value.companies.map((company) => <option value={company.cik} key={company.cik}>
              {company.ticker} — {company.name}</option>)}
          </select></div>
      </div>
    </section>
    {!result ? <Notice error={!!resource.error}>{resource.error || "Loading filing history…"}</Notice> :
      <section className="panel research-section">
        <div className="panel-heading"><div><h2>{result.company.ticker} filing history</h2>
          <p>{result.total} eligible filings · {result.with_qualified_facts} with qualified facts · {result.unverified_acceptance} with unverified acceptance</p>
        </div><ExportButton action={() => downloadCsv("filing-history", result.context,
          ["ticker", "page", "form", "period_end", "filed_on", "accepted_at", "qualified_facts", "accession", "filing_url"],
          result.filings.map((row) => [result.company.ticker, result.page, row.form_type, row.period_end, row.filed_on,
            row.accepted_at, row.qualified_facts, row.accession, row.filing_url]))} /></div>
        {result.filings.length === 0 ? <p className="research-body">No filings on this page.</p> : <div className="table-wrap" tabIndex={0} role="region" aria-label="Filing history table"><table>
          <thead><tr><th>Form</th><th>Period ended</th><th>Filed</th><th>Accepted (ET)</th><th>Qualified facts</th><th>SEC accession</th></tr></thead>
          <tbody>{result.filings.map((row) => <tr key={row.accession}>
            <th scope="row">{row.form_type}{row.form_type.endsWith("/A") && <small>Amendment</small>}</th>
            <td>{date(row.period_end)}</td><td>{date(row.filed_on)}</td>
            <td>{row.accepted_at ? accepted(row.accepted_at) : "Unverified"}</td>
            <td>{row.qualified_facts || "No qualified facts"}</td>
            <td><a className="view-link" href={row.filing_url} target="_blank" rel="noreferrer">{row.accession} <ExternalLink size={13} /></a></td>
          </tr>)}</tbody>
        </table></div>}
        <div className="table-pagination">
          <Button type="button" variant="outline" onClick={() => setPage(page - 1)} disabled={page <= 1}><ArrowLeft size={15} /> Previous</Button>
          <span>Page {page}</span>
          <Button type="button" variant="outline" onClick={() => setPage(page + 1)} disabled={page * result.page_size >= result.total}>Next <ArrowRight size={15} /></Button>
        </div>
      </section>}
  </>;
}

export function ResearchWorkspace({ page }: { page: Page }) {
  const [filters, setFilters] = useState<Filters>();
  const catalog = useResource<Model["DatasetList"]>("/datasets");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode");
    setFilters({
      mode: mode === "filed_by" || mode === "platform_snapshot" ? mode : "latest",
      date: params.get("filed_by") || "", version: params.get("dataset_version") || "",
    });
  }, []);
  const active = catalog.value?.versions.find((entry) => entry.version === catalog.value?.active_version);
  const chosen = filters?.mode === "platform_snapshot"
    ? catalog.value?.versions.find((entry) => entry.version === (filters.version || active?.version)) : active;
  const current = filters && { ...filters, date: filters.date || chosen?.filing_cutoff || "", version: filters.version || chosen?.version || "" };
  const share = current && reportingQuery(current).toString();
  const query = current && chosen && reportingQuery(current, chosen.version).toString();
  const limit = current?.mode === "filed_by" ? current.date : chosen?.filing_cutoff;
  function change(update: Partial<Filters>) {
    if (!current) return;
    const next = { ...current, ...update };
    setFilters(next);
    const query = reportingQuery(next);
    replaceParameters(Object.fromEntries(["mode", "filed_by", "dataset_version"].map((key) => [key, query.get(key) || ""])));
  }

  const [title, description] = views[page];
  return <Workspace route={`/${page}`} version={chosen?.version} query={share ? `?${share}` : undefined}>
    <header className="page-heading"><div><h1>{title}</h1><p>{description}</p></div></header>
    {current && active && <section className="panel controls" aria-label="Reporting filters">
      <div className="controls-row">
        <div className="field">
          <label id="research-mode">Reporting view</label>
          <div className="segmented" role="group" aria-labelledby="research-mode">
            {Object.entries(modes).map(([mode, name]) => <button type="button" key={mode}
              aria-pressed={mode === current.mode} onClick={() => change({ mode: mode as Mode })}>{name}</button>)}
          </div>
        </div>
        {current.mode === "filed_by" && <div className="field">
          <label htmlFor="research-cutoff">Filed by (New York time)</label>
          <input id="research-cutoff" type="date" max={active.filing_cutoff} value={current.date}
            onChange={(event) => change({ date: event.target.value })} />
        </div>}
        {current.mode === "platform_snapshot" && <div className="field">
          <label htmlFor="research-snapshot">Published dataset</label>
          <select id="research-snapshot" value={current.version} onChange={(event) => change({ version: event.target.value })}>
            {catalog.value?.versions.map((entry) => <option key={entry.version}>{entry.version}</option>)}
          </select>
        </div>}
        {chosen && <p className="filter-cutoff">SEC coverage through {date(chosen.filing_cutoff)}</p>}
      </div>
    </section>}
    {catalog.error && <Notice error>{catalog.error}</Notice>}
    {catalog.pending && <Notice>Loading published datasets…</Notice>}
    {catalog.value && current && !chosen && <Notice error>The requested snapshot is unavailable. Select a published dataset.</Notice>}
    {current && query && limit && <div key={query} className="research-section">
      {page === "overview" && <Overview query={query} filters={current} />}
      {page === "peers" && <Peers query={query} filters={current} limit={limit} />}
      {page === "funding" && <Funding query={query} limit={limit} />}
      {page === "data-quality" && chosen && <Filings query={query} dataset={chosen} />}
    </div>}
  </Workspace>;
}
