CREATE FUNCTION analytics.historical_borrowing_metrics(
    p_cik text,
    p_report_date date,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    metric text, value numeric, unit text, numerator numeric, denominator numeric,
    status text, debt_basis text, fact_ids bigint[], source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH balance AS (
        SELECT * FROM analytics.pilot_balance_sheet(p_cik, p_report_date, 'historical_balance_sheet', p_filed_by)
        WHERE metric = 'reported_debt'
    ), observations AS (
        SELECT * FROM analytics.pilot_facts(
            p_cik, NULL, p_report_date, 'consolidated', 'historical_balance_sheet', p_filed_by
        )
    ), leases AS (
        SELECT count(*) AS note_count, min(value) AS amount, min(concept) AS treatment,
               bool_or(status = 'conflicting_observations') AS has_conflict
        FROM observations
        WHERE concept IN ('finance_lease_liabilities', 'finance_lease_liabilities_outside_debt')
    ), borrowing AS (
        SELECT balance.value - CASE WHEN leases.treatment = 'finance_lease_liabilities'
                                    THEN leases.amount ELSE 0 END AS amount,
               balance.fact_ids AS debt_fact_ids, balance.source_accessions AS accessions,
               note.fact_ids AS lease_fact_ids,
               CASE leases.treatment
                   WHEN 'finance_lease_liabilities' THEN 'finance_leases_deducted'
                   WHEN 'finance_lease_liabilities_outside_debt' THEN 'finance_leases_outside_debt'
               END AS basis,
               CASE
                   WHEN balance.status IS NULL THEN 'unsupported_issuer'
                   WHEN balance.status <> 'available' THEN balance.status
                   WHEN leases.note_count > 1 OR leases.has_conflict THEN 'conflicting_observations'
                   WHEN leases.note_count = 0 OR leases.amount IS NULL THEN 'unverified_borrowing_basis'
                   WHEN note.source_accessions IS DISTINCT FROM balance.source_accessions THEN 'mixed_filings'
                   WHEN leases.amount < 0 OR balance.value < 0
                     OR (leases.treatment = 'finance_lease_liabilities' AND leases.amount > balance.value)
                       THEN 'invalid_borrowing_basis'
                   ELSE 'available'
               END AS quality
        FROM leases
        LEFT JOIN balance ON true
        LEFT JOIN observations AS note ON note.concept = leases.treatment
    ), definitions(metric, unit, operand) AS (
        VALUES
            ('borrowing_debt', 'USD', NULL),
            ('net_borrowing_debt', 'USD', 'cash_and_equivalents'),
            ('debt_to_assets', 'x', 'total_assets'),
            ('cash_to_debt', 'x', 'cash_and_equivalents')
    ), inputs AS (
        SELECT definition.metric, definition.unit, borrowing.amount AS debt,
               observation.value AS other_amount, borrowing.basis, borrowing.quality AS debt_quality,
               CASE
                   WHEN borrowing.quality <> 'available' THEN borrowing.quality
                   WHEN definition.operand IS NULL THEN 'available'
                   WHEN observation.status = 'conflicting_observations' THEN observation.status
                   WHEN observation.value IS NULL THEN 'missing_compatible_operands'
                   WHEN observation.source_accessions IS DISTINCT FROM borrowing.accessions THEN 'mixed_filings'
                   WHEN (definition.metric = 'debt_to_assets' AND observation.value <= 0)
                     OR (definition.metric = 'cash_to_debt' AND borrowing.amount <= 0)
                       THEN 'nonpositive_denominator'
                   ELSE 'available'
               END AS quality,
               borrowing.debt_fact_ids || borrowing.lease_fact_ids || observation.fact_ids AS fact_ids
        FROM definitions AS definition
        CROSS JOIN borrowing
        LEFT JOIN observations AS observation ON observation.concept = definition.operand
    )
    SELECT input.metric,
           CASE WHEN input.quality = 'available' THEN CASE input.metric
               WHEN 'borrowing_debt' THEN input.debt
               WHEN 'net_borrowing_debt' THEN input.debt - input.other_amount
               WHEN 'debt_to_assets' THEN input.debt / nullif(input.other_amount, 0)
               WHEN 'cash_to_debt' THEN input.other_amount / nullif(input.debt, 0)
           END END,
           input.unit,
           CASE WHEN input.quality IN ('available', 'nonpositive_denominator') THEN
               CASE WHEN input.metric = 'cash_to_debt' THEN input.other_amount ELSE input.debt END
           END,
           CASE WHEN input.quality IN ('available', 'nonpositive_denominator') THEN
               CASE WHEN input.metric = 'cash_to_debt' THEN input.debt
                    WHEN input.metric = 'debt_to_assets' THEN input.other_amount END
           END,
           input.quality, CASE WHEN input.debt_quality = 'available' THEN input.basis END,
           ARRAY(SELECT DISTINCT id FROM unnest(input.fact_ids) AS evidence(id) ORDER BY id),
           ARRAY(
               SELECT DISTINCT fact.accession
               FROM unnest(input.fact_ids) AS evidence(id)
               JOIN core.reported_facts AS fact ON fact.fact_id = evidence.id
               ORDER BY fact.accession
           )
    FROM inputs AS input
    ORDER BY input.metric;
$function$;
