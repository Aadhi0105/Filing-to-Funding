CREATE FUNCTION analytics.historical_cash_flow_metrics(
    p_cik text, p_fiscal_year integer, p_quarter integer,
    p_reporting_basis text, p_scope_key text, p_duration text, p_filed_by date
)
RETURNS TABLE (
    metric text, unit text, period_start date, period_end date, value numeric,
    status text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH cash_flow AS (
        SELECT quarter_start AS starts_on, quarter_end AS ends_on, operating_cash_flow, cash_capex, free_cash_flow,
               status, fact_ids, source_accessions
        FROM analytics.historical_quarter_cash_flow(
            p_cik, p_fiscal_year, p_quarter, p_reporting_basis, p_scope_key, p_filed_by
        )
        WHERE p_duration = 'quarter'
        UNION ALL
        SELECT period_start, period_end, operating_cash_flow, cash_capex, free_cash_flow,
               status, fact_ids, source_accessions
        FROM analytics.historical_ttm_cash_flow(
            p_cik, p_fiscal_year, p_quarter, p_reporting_basis, p_scope_key, p_filed_by
        )
        WHERE p_duration = 'ttm'
        UNION ALL
        SELECT period_start, period_end, operating_cash_flow, cash_capex, free_cash_flow,
               status, fact_ids, source_accessions
        FROM analytics.historical_annual_cash_flow(
            p_cik, p_fiscal_year, p_reporting_basis, p_scope_key, p_filed_by
        )
        WHERE p_duration IN ('annual', 'year')
    )
    SELECT items.metric, 'USD', flow.starts_on, flow.ends_on, items.value,
           coalesce(flow.status, 'unsupported_fiscal_period'),
           coalesce(flow.fact_ids, ARRAY[]::bigint[]), coalesce(flow.source_accessions, ARRAY[]::text[])
    FROM (SELECT 1) AS args
    LEFT JOIN cash_flow AS flow ON true
    CROSS JOIN LATERAL (VALUES
        ('operating_cash_flow', flow.operating_cash_flow),
        ('cash_capex', flow.cash_capex),
        ('free_cash_flow', flow.free_cash_flow)
    ) AS items(metric, value)
    UNION ALL
    SELECT ratio.metric, CASE ratio.metric WHEN 'fcf_margin' THEN 'fraction' ELSE 'x' END,
           ratio.period_start, ratio.period_end, ratio.value, ratio.status, ratio.fact_ids, ratio.source_accessions
    FROM analytics.historical_cash_flow_ratios(
        p_cik, p_fiscal_year, p_quarter, p_reporting_basis, p_scope_key, p_duration, p_filed_by
    ) AS ratio;
$function$;

CREATE FUNCTION analytics.historical_cash_flow_changes(
    p_cik text,
    p_fiscal_year integer,
    p_quarter integer,
    p_reporting_basis text,
    p_scope_key text,
    p_duration text DEFAULT 'quarter',
    p_filed_by date DEFAULT NULL,
    p_prior_reporting_basis text DEFAULT NULL,
    p_prior_scope_key text DEFAULT NULL
)
RETURNS TABLE (
    metric text, unit text, prior_start date, prior_end date, current_start date, current_end date,
    prior_value numeric, current_value numeric, absolute_change numeric, percentage_growth numeric,
    status text, growth_status text, prior_status text, current_status text,
    prior_fact_ids bigint[], current_fact_ids bigint[], prior_accessions text[], current_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH parameters AS (
        SELECT CASE WHEN p_fiscal_year BETWEEN 1901 AND 9999 THEN p_fiscal_year - 1 END AS prior_year,
               coalesce(p_prior_reporting_basis, p_reporting_basis) AS prior_basis,
               coalesce(p_prior_scope_key, p_scope_key) AS prior_scope
    ), comparisons AS (
        SELECT current.metric, current.unit,
               prior.period_start AS prior_start, prior.period_end AS prior_end,
               current.period_start AS current_start, current.period_end AS current_end,
               prior.value AS prior_value, current.value AS current_value,
               prior.status AS prior_status, current.status AS current_status,
               prior.fact_ids AS prior_fact_ids, current.fact_ids AS current_fact_ids,
               prior.source_accessions AS prior_accessions, current.source_accessions AS current_accessions,
               CASE
                   WHEN (params.prior_basis, params.prior_scope) IS DISTINCT FROM (p_reporting_basis, p_scope_key)
                       THEN 'incompatible_reporting_scope'
                   WHEN current.status <> 'available' OR prior.status <> 'available'
                       THEN 'unavailable_operand'
                   WHEN prior.unit <> current.unit
                     OR (calendars.prior_weekly <> calendars.current_weekly
                         AND prior_calendar.calendar_type IS NOT NULL AND current_calendar.calendar_type IS NOT NULL)
                     OR abs((current.period_end - current.period_start) - (prior.period_end - prior.period_start))
                         > CASE WHEN calendars.prior_weekly AND calendars.current_weekly THEN 0 ELSE 1 END
                     OR abs(current.period_start - (prior.period_start + INTERVAL '1 year')::date) > calendars.date_tolerance
                     OR abs(current.period_end - (prior.period_end + INTERVAL '1 year')::date) > calendars.date_tolerance
                       THEN 'incompatible_fiscal_periods'
                   ELSE 'available'
               END AS quality
        FROM parameters AS params
        CROSS JOIN LATERAL analytics.historical_cash_flow_metrics(
            p_cik, p_fiscal_year, p_quarter, p_reporting_basis, p_scope_key, p_duration, p_filed_by
        ) AS current
        JOIN LATERAL analytics.historical_cash_flow_metrics(
            p_cik, params.prior_year, p_quarter, params.prior_basis, params.prior_scope, p_duration, p_filed_by
        ) AS prior USING (metric)
        LEFT JOIN analytics.fiscal_year_calendar(p_cik, p_fiscal_year) AS current_calendar ON true
        LEFT JOIN LATERAL analytics.fiscal_year_calendar(p_cik, params.prior_year) AS prior_calendar ON true
        CROSS JOIN LATERAL (
            SELECT coalesce(prior_calendar.calendar_type IN ('52_week_year', '53_week_year'), false) AS prior_weekly,
                   coalesce(current_calendar.calendar_type IN ('52_week_year', '53_week_year'), false) AS current_weekly,
                   CASE WHEN prior_calendar.calendar_type IN ('52_week_year', '53_week_year')
                          AND current_calendar.calendar_type IN ('52_week_year', '53_week_year')
                        THEN 7 ELSE 1 END AS date_tolerance
        ) AS calendars
    )
    SELECT result.metric, result.unit, result.prior_start, result.prior_end, result.current_start, result.current_end,
           result.prior_value, result.current_value,
           CASE WHEN quality = 'available' THEN result.current_value - result.prior_value END,
           CASE WHEN quality = 'available' AND result.prior_value > 0
                THEN (result.current_value - result.prior_value) * 100 / result.prior_value END,
           quality,
           CASE WHEN quality <> 'available' THEN quality
                WHEN result.prior_value <= 0 THEN 'nonpositive_prior_value'
                ELSE 'available' END,
           result.prior_status, result.current_status,
           result.prior_fact_ids, result.current_fact_ids, result.prior_accessions, result.current_accessions
    FROM comparisons AS result
    ORDER BY result.metric;
$function$;
