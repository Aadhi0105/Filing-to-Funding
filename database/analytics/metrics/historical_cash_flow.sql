CREATE FUNCTION analytics.historical_quarter_cash_flow(
    p_cik text,
    p_fiscal_year integer,
    p_quarter integer,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    quarter_start date, quarter_end date, operating_cash_flow numeric, cash_capex numeric,
    free_cash_flow numeric, status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    SELECT *
    FROM analytics.pilot_quarter_cash_flow(
        p_cik, p_fiscal_year, p_quarter,
        (
            SELECT starts_on FROM core.reporting_periods
            WHERE cik = p_cik AND fiscal_year = p_fiscal_year AND fiscal_quarter = 1
        ),
        p_reporting_basis, p_scope_key, p_filed_by
    );
$function$;

CREATE FUNCTION analytics.historical_ttm_cash_flow(
    p_cik text,
    p_fiscal_year integer,
    p_quarter integer,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    period_start date, period_end date, operating_cash_flow numeric, cash_capex numeric,
    free_cash_flow numeric, status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH requested AS (
        SELECT step,
               p_fiscal_year - CASE WHEN step >= p_quarter THEN 1 ELSE 0 END AS fiscal_year,
               CASE WHEN step >= p_quarter THEN p_quarter - step + 4 ELSE p_quarter - step END AS quarter
        FROM generate_series(0, 3) AS offsets(step)
        WHERE p_quarter BETWEEN 1 AND 4
    ), quarters AS (
        SELECT requested.step, result.*,
               lag(result.quarter_end) OVER (ORDER BY requested.step DESC) AS earlier_quarter_end
        FROM requested
        CROSS JOIN LATERAL analytics.historical_quarter_cash_flow(
            p_cik, requested.fiscal_year, requested.quarter, p_reporting_basis, p_scope_key, p_filed_by
        ) AS result
    ), totals AS (
        SELECT min(quarter_start) AS starts_on, max(quarter_end) AS ends_on,
               sum(operating_cash_flow) AS cfo, sum(cash_capex) AS capex, sum(free_cash_flow) AS fcf,
               CASE
                   WHEN count(*) <> 4 THEN 'unsupported_fiscal_period'
                   WHEN bool_or(status = 'conflicting_observations') THEN 'conflicting_observations'
                   WHEN count(*) FILTER (WHERE status = 'available') <> 4
                        OR count(*) FILTER (
                            WHERE step < 3 AND quarter_start = earlier_quarter_end + 1
                        ) <> 3 THEN 'missing_compatible_quarters'
                   ELSE 'available'
               END AS quality
        FROM quarters
    )
    SELECT CASE WHEN quality = 'available' THEN starts_on END,
           CASE WHEN quality = 'available' THEN ends_on END,
           CASE WHEN quality = 'available' THEN cfo END,
           CASE WHEN quality = 'available' THEN capex END,
           CASE WHEN quality = 'available' THEN fcf END,
           quality,
           ARRAY(SELECT DISTINCT id FROM quarters CROSS JOIN LATERAL unnest(quarters.fact_ids) AS facts(id) ORDER BY id),
           ARRAY(
               SELECT DISTINCT accession FROM quarters
               CROSS JOIN LATERAL unnest(quarters.source_accessions) AS filings(accession) ORDER BY accession
           )
    FROM totals;
$function$;
