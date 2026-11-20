"""Read models for the overview, peer comparison, rates, and filing history."""

from collections import Counter
from datetime import date

from apps.api import company_data as company

PEER_METRICS = ("free_cash_flow", "working_capital", "current_ratio")
SCOPE_NOTES = {
    "AOS": (date(2026, 9, 30), "September 2026 includes the China business and reflects the Leonard Valve acquisition."),
    "DOV": (date(2025, 9, 30), "Cash flow uses continuing operations following the Environmental Solutions Group divestiture."),
    "IEX": (date(2026, 9, 30), "September 2026 cash excludes restricted cash. Earnings reflect revised rebate estimates."),
    "ITW": (date(2024, 12, 31), "Inventory reporting changed to FIFO in 2024."),
    "LECO": (date(2025, 12, 31), "Recent acquisitions affect comparisons over time. Borrowing ratios require a separate lease review."),
    "ROK": (date(2026, 9, 30), "FY2026 includes the Sensia transition. Rockwell's fiscal year ends in September."),
}

ELIGIBLE = """
    (%(cutoff)s::date IS NULL OR (
        f.filed_on <= %(cutoff)s AND
        f.accepted_at < ((%(cutoff)s::date + 1)::timestamp AT TIME ZONE 'America/New_York')
    ))
"""


def reported_periods(connection, cik, duration, cutoff):
    reports = connection.execute(f"""
        SELECT DISTINCT p.ends_on
        FROM core.filings AS f JOIN core.reporting_periods AS p ON p.period_id = f.report_period_id
        WHERE f.cik = %(cik)s AND {ELIGIBLE}
    """, {"cik": cik, "cutoff": cutoff}).fetchall()
    ends = {report["ends_on"] for report in reports}
    return [period for period in company.period_rows(connection, cik, duration, cutoff)
            if period["period_end"] in ends]


def metrics_for(connection, dataset, issuer, period, duration, cutoff):
    cik = issuer["cik"]
    flow = company.cash_flow(connection, dataset, cik, period, duration, cutoff)
    return {metric["metric"]: metric for metric in
            company.selected_metrics(connection, dataset, cik, period, duration, cutoff, flow)}


def overview(connection, dataset, cutoff):
    result = []
    for issuer in company.company_rows(connection, cutoff):
        period = next(iter(reported_periods(connection, issuer["cik"], "quarter", cutoff)), None)
        metrics = metrics_for(connection, dataset, issuer, period, "quarter", cutoff) if period else {}
        since, note = SCOPE_NOTES.get(issuer["ticker"], (date.max, None))
        result.append({"company": issuer, "period": period,
                       "note": note if period and period["period_end"] >= since else None,
                       "metrics": [metrics[key] for key in PEER_METRICS if key in metrics]})
    return result


def peers(connection, dataset, cutoff, duration, period_end, metric):
    periods_by_issuer = [
        (issuer, reported_periods(connection, issuer["cik"], duration, cutoff))
        for issuer in company.company_rows(connection, cutoff)
    ]
    if period_end is None:
        latest_ends = Counter(periods[0]["period_end"] for _, periods in periods_by_issuer if periods)
        period_end = max(latest_ends, key=lambda end: (latest_ends[end], end),
                         default=cutoff or dataset.filing_cutoff)
    result = []
    for issuer, periods in periods_by_issuer:
        period = next((row for row in periods if row["period_end"] <= period_end), None)
        item = {"company": issuer, "period": period, "metric": None, "status": "no_eligible_filing",
                "window_start": None, "reporting_basis": None}
        if period and period["period_end"] != period_end:
            item["status"] = "different_period_end"
        elif period:
            candidate = metrics_for(connection, dataset, issuer, period, duration, cutoff)[metric]
            item.update(window_start=candidate["period_start"], reporting_basis=candidate["reporting_basis"])
            transition = candidate["scope_key"] == "rok_sensia_transition_year"
            if candidate["reporting_basis"] != "consolidated":
                item["status"] = "different_reporting_basis"
            elif transition:
                item["status"] = "structural_transition"
            else:
                item.update(metric=candidate, status=candidate["status"])
        result.append(item)
    # Compare durations using the actual calculated window. An instant has no start date.
    starts = [row["metric"]["period_start"] for row in result
              if row["metric"] and row["metric"]["value"] is not None and row["metric"]["period_start"]]
    if metric == "free_cash_flow" and starts:
        common_start = max(set(starts), key=lambda start: (starts.count(start), start))
        for row in result:
            candidate = row["metric"]
            if candidate and candidate["value"] is not None and candidate["period_start"] != common_start:
                row.update(metric=None, status="different_period_start")
    return {"period_end": period_end, "rows": result}


def filing_history(connection, cik, cutoff, page):
    args = {"cik": cik, "cutoff": cutoff, "offset": (page - 1) * 10}
    summary = connection.execute(f"""
        SELECT count(*) AS total, count(*) FILTER (WHERE f.accepted_at IS NULL) AS unverified_acceptance,
               count(*) FILTER (WHERE EXISTS (SELECT FROM core.reported_facts rf
                   WHERE rf.accession = f.accession AND rf.taxonomy = 'filing-statement-v1')) AS with_qualified_facts
        FROM core.filings f WHERE f.cik = %(cik)s AND {ELIGIBLE}
    """, args).fetchone()
    rows = connection.execute(f"""
        SELECT f.accession, f.form_type, f.filed_on, f.accepted_at, f.filing_url, p.ends_on AS period_end,
               (SELECT count(*) FROM core.reported_facts rf WHERE rf.accession = f.accession
                AND rf.taxonomy = 'filing-statement-v1') AS qualified_facts
        FROM core.filings f JOIN core.reporting_periods p ON p.period_id = f.report_period_id
        WHERE f.cik = %(cik)s AND {ELIGIBLE}
        ORDER BY f.filed_on DESC, f.accepted_at DESC NULLS LAST, f.accession DESC LIMIT 10 OFFSET %(offset)s
    """, args).fetchall()
    return {**summary, "page": page, "page_size": 10, "filings": rows}


def treasury_cutoff(context, curve_date: date | None):
    limit = context.filed_by or context.filing_cutoff
    if curve_date is not None and curve_date > limit:
        raise ValueError(f"Choose a Treasury date on or before {limit.isoformat()}.")
    return curve_date or limit


def treasury_curve(connection, cutoff):
    return connection.execute("SELECT * FROM analytics.treasury_curve(%s)", [cutoff]).fetchone()
