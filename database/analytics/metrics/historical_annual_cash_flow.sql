CREATE FUNCTION analytics.fiscal_year_calendar(p_cik text, p_fiscal_year integer)
RETURNS TABLE (period_start date, period_end date, period_days integer, calendar_type text)
LANGUAGE sql
STABLE
AS $function$
    SELECT starts_on, ends_on, ends_on - starts_on + 1,
           CASE
               WHEN ends_on + 1 = (starts_on + INTERVAL '1 year')::date THEN 'calendar_year'
               WHEN ends_on - starts_on + 1 = 364 THEN '52_week_year'
               WHEN ends_on - starts_on + 1 = 371 THEN '53_week_year'
               WHEN ends_on - starts_on + 1 < 364 THEN 'short_fiscal_year'
               ELSE 'unsupported_fiscal_calendar'
           END
    FROM core.reporting_periods
    WHERE cik = p_cik AND fiscal_year = p_fiscal_year AND fiscal_quarter IS NULL;
$function$;

CREATE OR REPLACE FUNCTION analytics.historical_quarter_cash_flow(
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
    WITH calendar AS (
        SELECT * FROM analytics.fiscal_year_calendar(p_cik, p_fiscal_year)
        WHERE calendar_type IN ('short_fiscal_year', 'unsupported_fiscal_calendar')
    )
    SELECT cash_flow.*
    FROM analytics.pilot_quarter_cash_flow(
        p_cik, p_fiscal_year, p_quarter,
        (
            SELECT starts_on FROM core.reporting_periods
            WHERE cik = p_cik AND fiscal_year = p_fiscal_year AND fiscal_quarter = 1
        ),
        p_reporting_basis, p_scope_key, p_filed_by
    ) AS cash_flow
    WHERE NOT EXISTS (SELECT FROM calendar)
    UNION ALL
    SELECT NULL::date, NULL::date, NULL::numeric, NULL::numeric, NULL::numeric,
           'unsupported_fiscal_period', ARRAY[]::bigint[], ARRAY[]::text[]
    FROM calendar;
$function$;

CREATE FUNCTION analytics.historical_annual_cash_flow(
    p_cik text,
    p_fiscal_year integer,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    period_start date, period_end date, period_days integer, calendar_type text,
    operating_cash_flow numeric, cash_capex numeric, free_cash_flow numeric,
    status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH calendar AS (
        SELECT year.*
        FROM (SELECT 1) AS args
        LEFT JOIN analytics.fiscal_year_calendar(p_cik, p_fiscal_year) AS year ON true
    ), operands AS (
        SELECT fact.*
        FROM calendar
        CROSS JOIN LATERAL analytics.pilot_facts(
            p_cik, calendar.period_start, calendar.period_end, p_reporting_basis, p_scope_key, p_filed_by
        ) AS fact
        WHERE calendar.calendar_type IN ('calendar_year', '52_week_year', '53_week_year')
          AND fact.concept IN ('operating_cash_flow', 'cash_capex_outflow')
    ), evidence AS (
        SELECT fact.fact_id, fact.accession
        FROM operands
        CROSS JOIN LATERAL unnest(operands.fact_ids) AS linked(fact_id)
        JOIN core.reported_facts AS fact USING (fact_id)
    ), amounts AS (
        SELECT max(value) FILTER (WHERE concept = 'operating_cash_flow') AS cfo,
               max(value) FILTER (WHERE concept = 'cash_capex_outflow') AS capex,
               bool_or(status = 'conflicting_observations') AS has_conflict
        FROM operands
    ), classified AS (
        SELECT calendar.*, amounts.*,
               CASE
                   WHEN coalesce(calendar.calendar_type, '') NOT IN ('calendar_year', '52_week_year', '53_week_year')
                       OR p_reporting_basis IS NULL OR p_reporting_basis NOT IN (
                           'consolidated', 'continuing_operations', 'discontinued_operations'
                       ) THEN 'unsupported_fiscal_period'
                   WHEN has_conflict THEN 'conflicting_observations'
                   WHEN cfo IS NULL OR capex IS NULL THEN 'missing_compatible_operands'
                   WHEN (SELECT count(DISTINCT accession) FROM evidence) <> 1 THEN 'mixed_filings'
                   WHEN capex > 0 THEN 'invalid_capex_basis'
                   ELSE 'available'
               END AS quality
        FROM calendar CROSS JOIN amounts
    )
    SELECT result.period_start, result.period_end, result.period_days, result.calendar_type,
           CASE WHEN quality = 'available' THEN cfo END,
           CASE WHEN quality = 'available' THEN -capex END,
           CASE WHEN quality = 'available' THEN cfo + capex END,
           quality,
           ARRAY(SELECT DISTINCT fact_id FROM evidence ORDER BY fact_id),
           ARRAY(SELECT DISTINCT accession FROM evidence ORDER BY accession)
    FROM classified AS result;
$function$;

CREATE FUNCTION analytics.historical_annual_cash_flow_ratios(
    p_cik text,
    p_fiscal_year integer,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    metric text, period_start date, period_end date, value numeric,
    numerator numeric, denominator numeric, status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH annual AS (
        SELECT * FROM analytics.historical_annual_cash_flow(
            p_cik, p_fiscal_year, p_reporting_basis, p_scope_key, p_filed_by
        )
    ), operating AS (
        -- Cash conversion only requires operating cash flow and same-filing net income.
        SELECT fact.*
        FROM annual
        CROSS JOIN LATERAL analytics.pilot_facts(
            p_cik, annual.period_start, annual.period_end, p_reporting_basis, p_scope_key, p_filed_by
        ) AS fact
        WHERE annual.status <> 'unsupported_fiscal_period' AND fact.concept = 'operating_cash_flow'
    ), numerators AS (
        SELECT 'fcf_margin' AS metric, 'revenue' AS denominator_concept,
               annual.period_start, annual.period_end, annual.free_cash_flow AS amount,
               annual.status AS cash_flow_status, annual.fact_ids, annual.source_accessions
        FROM annual
        UNION ALL
        SELECT 'cash_conversion', 'net_income', annual.period_start, annual.period_end,
               operating.value,
               CASE
                   WHEN annual.status = 'unsupported_fiscal_period' THEN annual.status
                   WHEN operating.status IS NULL THEN 'missing_compatible_operands'
                   WHEN operating.status <> 'available' THEN operating.status
                   WHEN cardinality(operating.source_accessions) <> 1 THEN 'mixed_filings'
                   ELSE 'available'
               END,
               operating.fact_ids, operating.source_accessions
        FROM annual LEFT JOIN operating ON true
    ), evaluated AS (
        SELECT flow.*, denominator.amount AS denominator_amount, denominator.fact_ids AS denominator_ids,
               CASE
                   WHEN flow.cash_flow_status <> 'available' THEN flow.cash_flow_status
                   WHEN denominator.value_count > 1 THEN 'conflicting_observations'
                   WHEN denominator.value_count = 0 THEN 'missing_compatible_denominator'
                   WHEN denominator.amount <= 0 THEN 'nonpositive_denominator'
                   ELSE 'available'
               END AS quality
        FROM numerators AS flow
        CROSS JOIN LATERAL (
            SELECT min(fact.value) AS amount, count(DISTINCT fact.value) AS value_count,
                   array_agg(fact.fact_id ORDER BY fact.fact_id) AS fact_ids
            FROM core.reported_facts AS fact
            WHERE flow.cash_flow_status = 'available'
              AND fact.accession = flow.source_accessions[1]
              AND fact.period_start = flow.period_start AND fact.period_end = flow.period_end
              AND fact.taxonomy = 'filing-statement-v1' AND fact.concept = flow.denominator_concept
              AND fact.unit = 'USD' AND fact.dimensions = '{}'::jsonb
              AND fact.reporting_basis = p_reporting_basis AND fact.scope_key = p_scope_key
        ) AS denominator
    )
    SELECT result.metric, result.period_start, result.period_end,
           CASE WHEN quality = 'available' THEN amount / nullif(denominator_amount, 0) END,
           CASE WHEN cash_flow_status = 'available' THEN amount END,
           CASE WHEN quality IN ('available', 'nonpositive_denominator') THEN denominator_amount END,
           quality,
           ARRAY(SELECT DISTINCT id FROM unnest(fact_ids || denominator_ids) AS evidence(id) ORDER BY id),
           coalesce(source_accessions, ARRAY[]::text[])
    FROM evaluated AS result
    ORDER BY result.metric;
$function$;

ALTER FUNCTION analytics.historical_cash_flow_ratios(text, integer, integer, text, text, text, date)
    RENAME TO quarter_and_ttm_cash_flow_ratios;

CREATE FUNCTION analytics.historical_cash_flow_ratios(
    p_cik text,
    p_fiscal_year integer,
    p_quarter integer,
    p_reporting_basis text,
    p_scope_key text,
    p_duration text DEFAULT 'quarter',
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    metric text, period_start date, period_end date, value numeric,
    numerator numeric, denominator numeric, status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    SELECT * FROM analytics.historical_annual_cash_flow_ratios(
        p_cik, p_fiscal_year, p_reporting_basis, p_scope_key, p_filed_by
    )
    WHERE p_duration IN ('annual', 'year')
    UNION ALL
    SELECT * FROM analytics.quarter_and_ttm_cash_flow_ratios(
        p_cik, p_fiscal_year, p_quarter, p_reporting_basis, p_scope_key, p_duration, p_filed_by
    )
    WHERE p_duration IS DISTINCT FROM 'annual' AND p_duration IS DISTINCT FROM 'year'
    ORDER BY metric;
$function$;
