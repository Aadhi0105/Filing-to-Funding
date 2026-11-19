CREATE FUNCTION analytics.pilot_balance_sheet(
    p_cik text,
    p_report_date date,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    metric text,
    value numeric,
    unit text,
    status text,
    fact_ids bigint[],
    source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH observations AS (
        SELECT *
        FROM analytics.pilot_facts(p_cik, NULL, p_report_date, 'consolidated', p_scope_key, p_filed_by)
    ), debt_components AS (
        -- The reviewed ITW and Dover rows already cover current borrowings.
        SELECT CASE WHEN p_cik = '0001024478'
                   THEN ARRAY['short_term_debt', 'noncurrent_debt', 'current_portion_long_term_debt']
                   ELSE ARRAY['short_term_debt', 'noncurrent_debt']
               END AS keys
        WHERE p_cik IN ('0000049826', '0000029905', '0001024478')
    ), specs(metric, unit, keys) AS (
        VALUES
            ('working_capital', 'USD', ARRAY['current_assets', 'current_liabilities']),
            ('current_ratio', 'x', ARRAY['current_assets', 'current_liabilities']),
            ('cash_ratio', 'x', ARRAY['cash_and_equivalents', 'current_liabilities'])
        UNION ALL
        SELECT 'reported_debt', 'USD', debt.keys FROM debt_components AS debt
        UNION ALL
        SELECT 'reported_net_debt', 'USD', ARRAY['cash_and_equivalents'] || debt.keys
        FROM debt_components AS debt
        UNION ALL
        SELECT 'borrowing_debt_excluding_finance_leases', 'USD', ARRAY['finance_lease_liabilities'] || debt.keys
        FROM debt_components AS debt WHERE p_cik = '0001024478'
        UNION ALL
        SELECT 'net_borrowing_debt_excluding_finance_leases', 'USD',
               ARRAY['cash_and_equivalents', 'finance_lease_liabilities'] || debt.keys
        FROM debt_components AS debt WHERE p_cik = '0001024478'
    ), inputs AS (
        SELECT spec.metric, spec.unit, required.position,
               obs.value, obs.status, obs.fact_ids
        FROM specs AS spec
        CROSS JOIN LATERAL unnest(spec.keys) WITH ORDINALITY AS required(concept, position)
        LEFT JOIN observations AS obs ON obs.concept = required.concept
    ), metrics AS (
        SELECT input.metric, input.unit,
               array_agg(input.value ORDER BY input.position) AS amounts,
               bool_or(input.status = 'conflicting_observations') AS has_conflict,
               bool_or(input.value IS NULL) AS has_missing
        FROM inputs AS input
        GROUP BY input.metric, input.unit
    ), evidence AS (
        SELECT input.metric, array_agg(DISTINCT fact.fact_id ORDER BY fact.fact_id) AS fact_ids,
               array_agg(DISTINCT fact.accession ORDER BY fact.accession) AS accessions
        FROM inputs AS input
        CROSS JOIN LATERAL unnest(input.fact_ids) AS source(fact_id)
        JOIN core.reported_facts AS fact USING (fact_id)
        GROUP BY input.metric
    ), classified AS (
        SELECT m.*, coalesce(e.fact_ids, ARRAY[]::bigint[]) AS fact_ids,
               coalesce(e.accessions, ARRAY[]::text[]) AS accessions,
               CASE
                   WHEN m.has_conflict THEN 'conflicting_observations'
                   WHEN m.has_missing THEN 'missing_compatible_operands'
                   WHEN cardinality(e.accessions) <> 1 THEN 'mixed_filings'
                   WHEN m.metric IN ('current_ratio', 'cash_ratio') AND m.amounts[2] <= 0
                       THEN 'nonpositive_denominator'
                   ELSE 'available'
               END AS quality
        FROM metrics AS m
        LEFT JOIN evidence AS e USING (metric)
    )
    SELECT result.metric,
           CASE WHEN result.quality = 'available' THEN
               CASE result.metric
                   WHEN 'working_capital' THEN result.amounts[1] - result.amounts[2]
                   WHEN 'current_ratio' THEN result.amounts[1] / result.amounts[2]
                   WHEN 'cash_ratio' THEN result.amounts[1] / result.amounts[2]
                   WHEN 'reported_debt'
                       THEN (SELECT sum(amount) FROM unnest(result.amounts) AS item(amount))
                   WHEN 'reported_net_debt'
                       THEN (SELECT sum(amount) FROM unnest(result.amounts[2:]) AS item(amount)) - result.amounts[1]
                   WHEN 'borrowing_debt_excluding_finance_leases'
                       THEN (SELECT sum(amount) FROM unnest(result.amounts[2:]) AS item(amount)) - result.amounts[1]
                   WHEN 'net_borrowing_debt_excluding_finance_leases'
                       THEN (SELECT sum(amount) FROM unnest(result.amounts[3:]) AS item(amount))
                            - result.amounts[1] - result.amounts[2]
               END
           END,
           result.unit, result.quality, result.fact_ids, result.accessions
    FROM classified AS result
    ORDER BY result.metric;
$function$;
