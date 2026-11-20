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
    WITH definitions(metric, denominator_concept) AS (
        VALUES ('fcf_margin', 'revenue'), ('cash_conversion', 'net_income')
    ), requested AS (
        SELECT step,
               p_fiscal_year - CASE WHEN step >= p_quarter THEN 1 ELSE 0 END AS fiscal_year,
               CASE WHEN step >= p_quarter THEN p_quarter - step + 4 ELSE p_quarter - step END AS quarter
        FROM generate_series(0, CASE WHEN p_duration = 'ttm' THEN 3 ELSE 0 END) AS offsets(step)
        WHERE p_duration IN ('quarter', 'ttm') AND p_quarter BETWEEN 1 AND 4
          AND p_fiscal_year BETWEEN 1900 AND 9999
    ), quarters AS (
        SELECT requested.step, requested.quarter AS quarter_number, first_quarter.starts_on AS fiscal_start,
               cash_flow.*,
               lag(cash_flow.quarter_end) OVER (ORDER BY requested.step DESC) AS earlier_quarter_end
        FROM requested
        CROSS JOIN LATERAL analytics.historical_quarter_cash_flow(
            p_cik, requested.fiscal_year, requested.quarter, p_reporting_basis, p_scope_key, p_filed_by
        ) AS cash_flow
        LEFT JOIN core.reporting_periods AS first_quarter
          ON first_quarter.cik = p_cik AND first_quarter.fiscal_year = requested.fiscal_year
         AND first_quarter.fiscal_quarter = 1
    ), cfo_inputs AS (
        -- Cash conversion needs only operating cash flow. Capex can be unavailable.
        SELECT quarter.step, period.sign, fact.*
        FROM quarters AS quarter
        CROSS JOIN LATERAL (
            SELECT quarter.quarter_end AS ends_on, 1 AS sign
            UNION ALL
            SELECT quarter.quarter_start - 1, -1 WHERE quarter.quarter_number > 1
        ) AS period
        LEFT JOIN LATERAL (
            SELECT * FROM analytics.pilot_facts(
                p_cik, quarter.fiscal_start, period.ends_on, p_reporting_basis, p_scope_key, p_filed_by
            )
            WHERE concept = 'operating_cash_flow'
        ) AS fact ON true
        WHERE quarter.status <> 'unsupported_fiscal_period'
    ), cfo_quarters AS (
        SELECT input.step, sum(input.sign * input.value) AS amount,
               CASE
                   WHEN bool_or(input.status = 'conflicting_observations') THEN 'conflicting_observations'
                   WHEN bool_or(input.value IS NULL) THEN 'missing_compatible_operands'
                   WHEN bool_or(cardinality(input.source_accessions) <> 1) THEN 'mixed_filings'
                   ELSE 'available'
               END AS status
        FROM cfo_inputs AS input
        GROUP BY input.step
    ), numerators AS (
        SELECT 'fcf_margin' AS metric, quarter.step, quarter.quarter_start, quarter.quarter_end,
               quarter.earlier_quarter_end, quarter.free_cash_flow AS amount, quarter.status, quarter.fact_ids
        FROM quarters AS quarter
        UNION ALL
        SELECT 'cash_conversion', quarter.step, quarter.quarter_start, quarter.quarter_end,
               quarter.earlier_quarter_end, cfo.amount, coalesce(cfo.status, quarter.status),
               ARRAY(
                   SELECT DISTINCT evidence.fact_id
                   FROM cfo_inputs AS input
                   CROSS JOIN LATERAL unnest(input.fact_ids) AS evidence(fact_id)
                   WHERE input.step = quarter.step
               )
        FROM quarters AS quarter
        LEFT JOIN cfo_quarters AS cfo ON cfo.step = quarter.step
    ), cash_evidence AS (
        SELECT numerator.metric, numerator.step, numerator.quarter_end, numerator.status, fact.*
        FROM numerators AS numerator
        CROSS JOIN LATERAL unnest(numerator.fact_ids) AS evidence(fact_id)
        JOIN core.reported_facts AS fact USING (fact_id)
    ), disclosures AS (
        -- A denominator must come from the filing and cumulative interval used for that cash-flow operand.
        SELECT DISTINCT evidence.metric, evidence.step, evidence.quarter_end, evidence.accession,
                        evidence.period_start, evidence.period_end
        FROM cash_evidence AS evidence
        WHERE evidence.status = 'available' AND evidence.concept = 'operating_cash_flow'
    ), denominator_evidence AS (
        SELECT disclosure.*,
               count(DISTINCT fact.value) AS value_count, min(fact.value) AS amount,
               array_agg(DISTINCT fact.fact_id) FILTER (WHERE fact.fact_id IS NOT NULL) AS fact_ids
        FROM disclosures AS disclosure
        JOIN definitions AS definition ON definition.metric = disclosure.metric
        LEFT JOIN core.reported_facts AS fact
          ON fact.accession = disclosure.accession
         AND fact.period_start = disclosure.period_start AND fact.period_end = disclosure.period_end
         AND fact.taxonomy = 'filing-statement-v1' AND fact.concept = definition.denominator_concept
         AND fact.unit = 'USD' AND fact.dimensions = '{}'::jsonb
         AND fact.reporting_basis = p_reporting_basis AND fact.scope_key = p_scope_key
        GROUP BY disclosure.metric, disclosure.step, disclosure.quarter_end,
                 disclosure.accession, disclosure.period_start, disclosure.period_end
    ), denominators AS (
        SELECT metric, step,
               sum(CASE WHEN period_end = quarter_end THEN amount ELSE -amount END) AS amount,
               bool_or(value_count <> 1) AS incomplete,
               bool_or(value_count > 1) AS conflicting
        FROM denominator_evidence
        GROUP BY metric, step
    ), combined AS (
        SELECT definition.metric,
               min(quarter.quarter_start) AS starts_on, max(quarter.quarter_end) AS ends_on,
               sum(quarter.amount) AS numerator,
               sum(denominator.amount) AS denominator,
               coalesce(bool_or(coalesce(denominator.incomplete, true)), true) AS denominator_incomplete,
               coalesce(bool_or(denominator.conflicting), false) AS denominator_conflicting,
               CASE
                   WHEN count(quarter.step) = 0 THEN 'unsupported_fiscal_period'
                   WHEN p_duration = 'quarter' THEN max(quarter.status)
                   WHEN bool_or(quarter.status = 'conflicting_observations') THEN 'conflicting_observations'
                   WHEN count(*) FILTER (WHERE quarter.status = 'available') <> 4
                     OR count(*) FILTER (WHERE quarter.step < 3
                                         AND quarter.quarter_start = quarter.earlier_quarter_end + 1) <> 3
                       THEN 'missing_compatible_quarters'
                   ELSE 'available'
               END AS cash_flow_status
        FROM definitions AS definition
        LEFT JOIN numerators AS quarter ON quarter.metric = definition.metric
        LEFT JOIN denominators AS denominator ON denominator.metric = definition.metric AND denominator.step = quarter.step
        GROUP BY definition.metric
    ), results AS (
        SELECT combined.*, CASE
            WHEN cash_flow_status <> 'available' THEN cash_flow_status
            WHEN denominator_conflicting THEN 'conflicting_observations'
            WHEN denominator_incomplete OR denominator IS NULL THEN 'missing_compatible_denominator'
            WHEN denominator <= 0 THEN 'nonpositive_denominator'
            ELSE 'available'
        END AS quality
        FROM combined
    ), lineage AS (
        SELECT evidence.metric, evidence.fact_id
        FROM cash_evidence AS evidence
        UNION
        SELECT evidence.metric, ids.fact_id
        FROM denominator_evidence AS evidence
        CROSS JOIN LATERAL unnest(evidence.fact_ids) AS ids(fact_id)
    )
    SELECT result.metric, result.starts_on, result.ends_on,
           CASE WHEN result.quality = 'available' THEN result.numerator / nullif(result.denominator, 0) END,
           CASE WHEN result.cash_flow_status = 'available' THEN result.numerator END,
           CASE WHEN result.cash_flow_status = 'available' AND NOT result.denominator_incomplete
                THEN result.denominator END,
           result.quality,
           ARRAY(SELECT fact_id FROM lineage WHERE metric = result.metric ORDER BY fact_id),
           ARRAY(
               SELECT DISTINCT fact.accession FROM lineage
               JOIN core.reported_facts AS fact USING (fact_id)
               WHERE lineage.metric = result.metric ORDER BY fact.accession
           )
    FROM results AS result
    ORDER BY result.metric;
$function$;
