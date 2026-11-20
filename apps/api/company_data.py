"""SQL reads for the company explorer. Financial calculations stay in PostgreSQL."""

from datetime import date

from fastapi import HTTPException

from apps.api.dataset_access import Dataset, Duration, reader

PERIODS_SQL = """
WITH periods AS (
    SELECT fiscal_year, fiscal_quarter AS quarter, starts_on AS period_start, ends_on AS period_end
    FROM core.reporting_periods WHERE cik = %(cik)s
), available AS (
    SELECT * FROM periods WHERE (quarter IS NULL) = %(annual)s
    UNION ALL
    SELECT yearly.fiscal_year, 4, prior.period_end + 1, yearly.period_end
    FROM periods AS yearly
    JOIN periods AS prior ON prior.fiscal_year = yearly.fiscal_year AND prior.quarter = 3
    WHERE NOT %(annual)s AND yearly.quarter IS NULL AND prior.period_end < yearly.period_end
      AND NOT EXISTS (SELECT FROM periods q WHERE q.fiscal_year = yearly.fiscal_year AND q.quarter = 4)
)
SELECT * FROM available
WHERE (%(cutoff)s::date IS NULL OR period_end <= %(cutoff)s)
ORDER BY period_end DESC, fiscal_year DESC LIMIT 36
"""
COMPANIES_SQL = """
SELECT issuer.cik, issuer.legal_name AS name, ticker.alias AS ticker
FROM core.issuers AS issuer
JOIN LATERAL (
    SELECT alias FROM core.issuer_aliases
    WHERE cik = issuer.cik AND alias_kind = 'ticker'
      AND (%(cutoff)s::date IS NULL OR valid_from <= %(cutoff)s)
      AND (valid_until IS NULL OR (%(cutoff)s::date IS NOT NULL AND valid_until > %(cutoff)s))
    ORDER BY valid_from DESC LIMIT 1
) AS ticker ON true
ORDER BY ticker.alias
"""


def company_rows(connection, cutoff):
    return connection.execute(COMPANIES_SQL, {"cutoff": cutoff}).fetchall()


def require_company(connection, cik, cutoff):
    for company in company_rows(connection, cutoff):
        if company["cik"] == cik:
            return company
    raise HTTPException(404, "Company unavailable in the selected dataset and cutoff")


def period_rows(connection, cik, duration: Duration, cutoff):
    return connection.execute(PERIODS_SQL, {
        "cik": cik, "annual": duration == "annual", "cutoff": cutoff,
    }).fetchall()


def flow_scope(cik, period):
    year, end = period["fiscal_year"], period["period_end"]
    if cik == "0000049826":
        return "consolidated", "itw_from_fifo_change" if year >= 2024 else "itw_before_fifo_change"
    if cik == "0001024478":
        return "consolidated", "rok_sensia_transition_year" if year >= 2026 else "rok_before_sensia_transition"
    if year == 2020:
        return "continuing_operations", "dov_2020_continuing_operations"
    if end >= date(2024, 9, 30):
        return "continuing_operations", "dov_excluding_esg"
    return "consolidated", "dov_including_esg"


FLOW_FN = {
    "annual": ("historical_annual_cash_flow", "period_start", "period_end"),
    "quarter": ("historical_quarter_cash_flow", "quarter_start", "quarter_end"),
    "ttm": ("historical_ttm_cash_flow", "period_start", "period_end"),
}
FLOW_METRICS = ("operating_cash_flow", "cash_capex", "free_cash_flow")
RATIO_UNITS = {"fcf_margin": "fraction", "cash_conversion": "x"}


def cash_flow(connection, dataset, cik, period, duration, cutoff):
    if duration == "annual" and not dataset.annual_and_revisions:
        return {metric: None for metric in FLOW_METRICS} | {
            "status": "unsupported_by_snapshot", "fact_ids": [], "source_accessions": [],
            "period_start": period["period_start"], "period_end": period["period_end"],
        }
    basis, scope = flow_scope(cik, period)
    args = [cik, period["fiscal_year"]]
    if duration != "annual":
        args.append(period["quarter"])
    args.extend([basis, scope, cutoff])
    name, starts, ends = FLOW_FN[duration]
    parameters = ", ".join(["%s"] * len(args))
    return connection.execute(f"""
        SELECT {starts} AS period_start, {ends} AS period_end, operating_cash_flow,
               cash_capex, free_cash_flow, status, fact_ids, source_accessions
        FROM analytics.{name}({parameters})
    """, args).fetchone()


def selected_metrics(connection, dataset, cik, period, duration, cutoff, flow):
    basis, scope = flow_scope(cik, period)
    result = [{
        "metric": name, "unit": "USD", "value": flow[name], "status": flow["status"],
        "period_start": flow["period_start"], "period_end": flow["period_end"],
        "fact_ids": flow["fact_ids"], "source_accessions": flow["source_accessions"],
        "reporting_basis": basis, "scope_key": scope,
    } for name in FLOW_METRICS]
    if duration == "annual" and not dataset.annual_and_revisions:
        ratios = [{
            "metric": metric, "status": "unsupported_by_snapshot", "value": None, "fact_ids": [],
            "source_accessions": [], "period_start": period["period_start"], "period_end": period["period_end"],
        } for metric in RATIO_UNITS]
    else:
        ratios = connection.execute("""
            SELECT * FROM analytics.historical_cash_flow_ratios(%s, %s, %s, %s, %s, %s, %s)
        """, [cik, period["fiscal_year"], period["quarter"], basis, scope, duration, cutoff]).fetchall()
    result.extend({
        **ratio, "unit": RATIO_UNITS[ratio["metric"]], "reporting_basis": basis, "scope_key": scope,
    } for ratio in ratios)
    end = period["period_end"]
    balances = connection.execute("""
        SELECT metric, value, unit, status, fact_ids, source_accessions, NULL::text AS debt_basis
        FROM analytics.pilot_balance_sheet(%s, %s, 'historical_balance_sheet', %s)
        WHERE metric IN ('working_capital', 'current_ratio', 'cash_ratio')
        UNION ALL
        SELECT metric, value, unit, status, fact_ids, source_accessions, debt_basis
        FROM analytics.historical_borrowing_metrics(%s, %s, %s)
        ORDER BY metric
    """, [cik, end, cutoff, cik, end, cutoff]).fetchall()
    result.extend({
        **balance, "period_start": None, "period_end": end,
        "reporting_basis": "consolidated", "scope_key": "historical_balance_sheet",
    } for balance in balances)
    return result


def revision_rows(connection, dataset, cik, end, cutoff):
    if not dataset.annual_and_revisions:
        return []
    return connection.execute("""
        SELECT * FROM analytics.filing_fact_revisions(%s, %s, %s)
        ORDER BY CASE concept WHEN 'operating_cash_flow' THEN 1 WHEN 'cash_and_equivalents' THEN 2 ELSE 3 END,
                 later_filed_on DESC, concept, later_accession, prior_accession
        LIMIT 40
    """, [cik, end, cutoff]).fetchall()


def sources_for(connection, metrics, revisions):
    ids = {item for row in metrics for item in row["fact_ids"]}
    ids.update(item for row in revisions for key in ("prior_fact_ids", "later_fact_ids") for item in row[key])
    if not ids:
        return []
    return connection.execute("""
        SELECT fact.fact_id, fact.accession, fact.concept, fact.value, fact.unit, fact.reported_decimals,
               fact.period_start, fact.period_end, fact.source_locator, filing.filing_url, filing.filed_on,
               filing.accepted_at, source.payload_sha256
        FROM core.reported_facts AS fact
        JOIN core.filings AS filing USING (accession)
        JOIN raw.source_fetches AS source ON source.fetch_id = fact.source_fetch_id
        WHERE fact.fact_id = ANY(%s) ORDER BY fact.fact_id
    """, [sorted(ids)]).fetchall()


def analysis(dataset: Dataset, cik, duration, cutoff, fiscal_year, quarter):
    with reader(dataset) as connection:
        company = require_company(connection, cik, cutoff)
        periods = period_rows(connection, cik, duration, cutoff)
        position = next((index for index, period in enumerate(periods)
                         if period["fiscal_year"] == fiscal_year and period["quarter"] == quarter), None)
        if position is None:
            raise HTTPException(404, "Fiscal period unavailable for the selected company and cutoff")
        selected = periods[position]
        flow = cash_flow(connection, dataset, cik, selected, duration, cutoff)
        series = []
        for period in reversed(periods[position:position + 9]):
            current = flow if period is selected else cash_flow(connection, dataset, cik, period, duration, cutoff)
            basis, scope = flow_scope(cik, period)
            series.append({
                **period, "period_start": current["period_start"], "period_end": period["period_end"],
                "value": current["free_cash_flow"], "status": current["status"],
                "reporting_basis": basis, "scope_key": scope, "source_accessions": current["source_accessions"],
            })
        metrics = selected_metrics(connection, dataset, cik, selected, duration, cutoff, flow)
        revisions = revision_rows(connection, dataset, cik, selected["period_end"], cutoff)
        return {
            "company": company, "period": selected, "duration": duration, "metrics": metrics, "series": series,
            "revisions": revisions, "sources": sources_for(connection, metrics, revisions),
        }
