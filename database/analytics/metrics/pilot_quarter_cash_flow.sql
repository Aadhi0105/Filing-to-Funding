CREATE FUNCTION analytics.pilot_quarter_cash_flow(
    p_cik text,
    p_fiscal_year integer,
    p_quarter integer,
    p_fiscal_year_start date,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    quarter_start date,
    quarter_end date,
    operating_cash_flow numeric,
    cash_capex numeric,
    free_cash_flow numeric,
    status text,
    fact_ids bigint[],
    source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH calendar AS (
        SELECT *
        FROM core.reporting_periods
        WHERE cik = p_cik AND fiscal_year = p_fiscal_year
    ), dates AS (
        SELECT coalesce(q.starts_on, CASE WHEN p_quarter = 4 AND fy.period_id IS NOT NULL
                                         THEN prev.ends_on + 1 END) AS starts_on,
               coalesce(q.ends_on, CASE WHEN p_quarter = 4 THEN fy.ends_on END) AS ends_on,
               prev.ends_on AS prior_end, fy.starts_on AS annual_start, fy.ends_on AS annual_end,
               q1.starts_on AS first_quarter_start
        FROM (SELECT 1) AS args
        LEFT JOIN calendar AS q ON q.fiscal_quarter = p_quarter
        LEFT JOIN calendar AS prev ON prev.fiscal_quarter = p_quarter - 1
        LEFT JOIN calendar AS fy ON fy.fiscal_quarter IS NULL
        LEFT JOIN calendar AS q1 ON q1.fiscal_quarter = 1
    ), checked_dates AS (
        SELECT dates.*,
               coalesce(
                   p_quarter BETWEEN 1 AND 4
                   AND p_reporting_basis IN ('consolidated', 'continuing_operations', 'discontinued_operations')
                   AND dates.ends_on >= dates.starts_on
                   AND (dates.annual_start IS NULL OR dates.annual_start = p_fiscal_year_start)
                   AND (dates.first_quarter_start IS NULL OR dates.first_quarter_start = p_fiscal_year_start)
                   AND (dates.annual_end IS NULL OR dates.ends_on <= dates.annual_end)
                   AND (p_quarter <> 4 OR dates.annual_end IS NULL OR dates.ends_on = dates.annual_end)
                   AND (
                       (p_quarter = 1 AND dates.starts_on = p_fiscal_year_start)
                       OR (
                           p_quarter > 1 AND p_fiscal_year_start <= dates.prior_end
                           AND dates.starts_on = dates.prior_end + 1
                       )
                   ), false
               ) AS valid
        FROM dates
    ), required_periods(period_role, period_end) AS (
        SELECT 'current', dates.ends_on FROM checked_dates AS dates WHERE dates.valid
        UNION ALL
        SELECT 'prior', dates.prior_end FROM checked_dates AS dates WHERE dates.valid AND p_quarter > 1
    ), operands AS (
        SELECT periods.period_role, fact.concept, fact.value, fact.status, fact.fact_ids
        FROM required_periods AS periods
        CROSS JOIN LATERAL analytics.pilot_facts(
            p_cik, p_fiscal_year_start, periods.period_end, p_reporting_basis, p_scope_key, p_filed_by
        ) AS fact
        WHERE fact.concept IN ('operating_cash_flow', 'cash_capex_outflow')
    ), evidence AS (
        SELECT operand.period_role, fact.fact_id, fact.accession
        FROM operands AS operand
        CROSS JOIN LATERAL unnest(operand.fact_ids) AS source(fact_id)
        JOIN core.reported_facts AS fact USING (fact_id)
    ), amounts AS (
        SELECT max(operand.value) FILTER (
                   WHERE operand.period_role = 'current' AND operand.concept = 'operating_cash_flow'
               ) AS current_cfo,
               max(operand.value) FILTER (
                   WHERE operand.period_role = 'prior' AND operand.concept = 'operating_cash_flow'
               ) AS prior_cfo,
               max(operand.value) FILTER (
                   WHERE operand.period_role = 'current' AND operand.concept = 'cash_capex_outflow'
               ) AS current_capex,
               max(operand.value) FILTER (
                   WHERE operand.period_role = 'prior' AND operand.concept = 'cash_capex_outflow'
               ) AS prior_capex,
               bool_or(operand.status = 'conflicting_observations') AS has_conflict
        FROM operands AS operand
    ), calculated AS (
        SELECT dates.starts_on, dates.ends_on,
               amounts.current_cfo - CASE WHEN p_quarter = 1 THEN 0 ELSE amounts.prior_cfo END AS cfo,
               -amounts.current_capex + CASE WHEN p_quarter = 1 THEN 0 ELSE amounts.prior_capex END AS capex,
               CASE
                   WHEN NOT dates.valid THEN 'unsupported_fiscal_period'
                   WHEN amounts.has_conflict THEN 'conflicting_observations'
                   WHEN amounts.current_cfo IS NULL OR amounts.current_capex IS NULL
                     OR (p_quarter > 1 AND (amounts.prior_cfo IS NULL OR amounts.prior_capex IS NULL))
                       THEN 'missing_compatible_operands'
                   WHEN EXISTS (
                       SELECT 1 FROM evidence GROUP BY period_role HAVING count(DISTINCT accession) > 1
                   ) THEN 'mixed_filings'
                   WHEN amounts.current_capex > 0 OR amounts.prior_capex > 0
                     OR (p_quarter > 1 AND amounts.current_capex > amounts.prior_capex)
                       THEN 'invalid_capex_basis'
                   ELSE 'available'
               END AS quality
        FROM checked_dates AS dates
        CROSS JOIN amounts
    )
    SELECT result.starts_on, result.ends_on,
           CASE WHEN result.quality = 'available' THEN result.cfo END,
           CASE WHEN result.quality = 'available' THEN result.capex END,
           CASE WHEN result.quality = 'available' THEN result.cfo - result.capex END,
           result.quality,
           ARRAY(SELECT DISTINCT evidence.fact_id FROM evidence ORDER BY evidence.fact_id),
           ARRAY(SELECT DISTINCT evidence.accession FROM evidence ORDER BY evidence.accession)
    FROM calculated AS result;
$function$;
