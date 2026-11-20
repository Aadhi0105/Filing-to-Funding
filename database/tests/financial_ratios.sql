\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
DECLARE
    failures text;
BEGIN
    IF (SELECT count(*) FROM core.reported_facts
        WHERE taxonomy = 'filing-statement-v1' AND concept IN ('revenue', 'net_income', 'total_assets')
    ) <> 349 THEN
        RAISE EXCEPTION 'The frozen earnings and total-assets evidence is incomplete';
    END IF;

    WITH cases(label, cik, fiscal_year, quarter, basis, scope, duration, cutoff, metric,
               expected_num, expected_denom, expected_value, expected_status) AS (
        VALUES
            ('ITW Q2 FCF margin', '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change',
             'quarter', DATE '2026-08-06', 'fcf_margin', 631000000, 4301000000, 0.146710, 'available'),
            ('ITW Q2 cash conversion', '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change',
             'quarter', DATE '2026-08-06', 'cash_conversion', 723000000, 815000000, 0.887117, 'available'),
            ('Dover Q3 before comparative', '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg',
             'quarter', DATE '2024-10-24', 'fcf_margin', NULL, NULL, NULL, 'missing_compatible_operands'),
            ('Dover Q3 continuing FCF margin', '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg',
             'quarter', DATE '2025-07-24', 'fcf_margin', 315490000, 1983542000, 0.159054, 'available'),
            ('Dover Q3 continuing cash conversion', '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg',
             'quarter', DATE '2025-07-24', 'cash_conversion', 353244000, 312896000, 1.128950, 'available'),
            ('Rockwell FY26 trailing FCF margin', '0001024478', 2026, 4, 'consolidated', 'rok_sensia_transition_year',
             'ttm', DATE '2026-11-12', 'fcf_margin', 1701000000, 8989000000, 0.189231, 'available'),
            ('Rockwell FY26 trailing cash conversion', '0001024478', 2026, 4, 'consolidated', 'rok_sensia_transition_year',
             'ttm', DATE '2026-11-12', 'cash_conversion', 1958000000, 1407000000, 1.391613, 'available'),
            ('Rockwell missing compatible trailing quarters', '0001024478', 2026, 3, 'consolidated', 'rok_sensia_transition_year',
             'ttm', DATE '2026-08-04', 'fcf_margin', NULL, NULL, NULL, 'missing_compatible_quarters')
    )
    SELECT string_agg(c.label, ', ') INTO failures
    FROM cases AS c
    LEFT JOIN LATERAL analytics.historical_cash_flow_ratios(
        c.cik, c.fiscal_year, c.quarter, c.basis, c.scope, c.duration, c.cutoff
    ) AS actual ON actual.metric = c.metric
    WHERE (actual.numerator, actual.denominator, round(actual.value, 6), actual.status)
       IS DISTINCT FROM (c.expected_num, c.expected_denom, c.expected_value, c.expected_status);
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Historical flow ratios failed for %', failures;
    END IF;

    WITH cases(label, cik, report_date, cutoff, metric, expected_num, expected_denom, expected_value,
               expected_status, expected_basis) AS (
        VALUES
            ('Rockwell debt to assets', '0001024478', DATE '2026-09-30', DATE '2026-11-12',
             'debt_to_assets', 3276000000, 11268000000, 0.290735, 'available', 'finance_leases_deducted'),
            ('Rockwell cash to debt', '0001024478', DATE '2026-09-30', DATE '2026-11-12',
             'cash_to_debt', 433000000, 3276000000, 0.132173, 'available', 'finance_leases_deducted'),
            ('Dover annual borrowing basis', '0000029905', DATE '2025-12-31', DATE '2026-02-13',
             'borrowing_debt', 3327972000, NULL, 3327972000, 'available', 'finance_leases_outside_debt'),
            ('Dover annual net borrowing debt', '0000029905', DATE '2025-12-31', DATE '2026-02-13',
             'net_borrowing_debt', 3327972000, NULL, 1651164000, 'available', 'finance_leases_outside_debt'),
            ('Rockwell older split lease balance', '0001024478', DATE '2022-09-30', DATE '2022-11-08',
             'cash_to_debt', NULL, NULL, NULL, 'unverified_borrowing_basis', NULL),
            ('ITW finance lease basis unverified', '0000049826', DATE '2026-06-30', DATE '2026-08-06',
             'cash_to_debt', NULL, NULL, NULL, 'unverified_borrowing_basis', NULL)
    )
    SELECT string_agg(c.label, ', ') INTO failures
    FROM cases AS c
    LEFT JOIN LATERAL analytics.historical_borrowing_metrics(c.cik, c.report_date, c.cutoff) AS actual
        ON actual.metric = c.metric
    WHERE (actual.numerator, actual.denominator, round(actual.value, 6), actual.status, actual.debt_basis)
       IS DISTINCT FROM (c.expected_num, c.expected_denom, c.expected_value, c.expected_status, c.expected_basis);
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Borrowing metrics failed for %', failures;
    END IF;

    IF NOT EXISTS (
        SELECT
        FROM analytics.historical_cash_flow_ratios(
            '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg', 'quarter', DATE '2025-07-24'
        )
        WHERE metric = 'cash_conversion'
          AND source_accessions = ARRAY['0000029905-24-000045', '0000029905-25-000024']
          AND cardinality(fact_ids) = 4
    ) THEN
        RAISE EXCEPTION 'Dover cash conversion lost evidence from either cumulative disclosure';
    END IF;
END
$test$;

SAVEPOINT absent_capex;
DELETE FROM core.reported_facts
WHERE taxonomy = 'filing-statement-v1' AND accession = '0000049826-26-000049'
  AND concept = 'cash_capex_outflow' AND period_end = DATE '2026-06-30';

DO $test$
DECLARE
    metric_result record;
BEGIN
    FOR metric_result IN
        SELECT * FROM analytics.historical_cash_flow_ratios(
            '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'quarter', DATE '2026-08-06'
        )
    LOOP
        IF metric_result.metric = 'fcf_margin' AND (metric_result.value IS NOT NULL
               OR metric_result.status <> 'missing_compatible_operands') THEN
            RAISE EXCEPTION 'FCF margin was calculated without capex';
        ELSIF metric_result.metric = 'cash_conversion'
           AND (metric_result.numerator, metric_result.denominator, metric_result.status)
               IS DISTINCT FROM (723000000::numeric, 815000000::numeric, 'available') THEN
            RAISE EXCEPTION 'Cash conversion depended on capex';
        END IF;
    END LOOP;
END
$test$;
ROLLBACK TO absent_capex;

SAVEPOINT different_accession;
INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at, acceptance_timezone, filing_url, metadata_fetch_id
)
SELECT '0000049826-26-999998', cik, report_period_id, '10-Q/A', filed_on,
       accepted_at + interval '1 minute', acceptance_timezone, filing_url, metadata_fetch_id
FROM core.filings WHERE accession = '0000049826-26-000049';

UPDATE core.reported_facts
SET accession = '0000049826-26-999998'
WHERE taxonomy = 'filing-statement-v1' AND accession = '0000049826-26-000049'
  AND concept = 'revenue' AND period_end = DATE '2026-06-30';

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_ratios(
           '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'quarter', DATE '2026-08-06'
        )
        WHERE metric = 'fcf_margin' AND numerator = 631000000 AND value IS NULL
          AND denominator IS NULL AND status = 'missing_compatible_denominator'
          AND NOT ('0000049826-26-999998' = ANY(source_accessions))
    ) THEN
        RAISE EXCEPTION 'The ratio borrowed revenue from an accession without the cash-flow operand';
    END IF;
END
$test$;
ROLLBACK TO different_accession;

SAVEPOINT loss_quarter;
UPDATE core.reported_facts
SET value = 700000000
WHERE taxonomy = 'filing-statement-v1' AND accession = '0000049826-26-000049'
  AND concept = 'net_income' AND period_end = DATE '2026-06-30';

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_ratios(
            '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'quarter', DATE '2026-08-06'
        )
        WHERE metric = 'cash_conversion' AND numerator = 723000000 AND denominator = -68000000
          AND status = 'nonpositive_denominator' AND value IS NULL
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_ratios(
            '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'ttm', DATE '2026-08-06'
        )
        WHERE metric = 'cash_conversion' AND denominator > 0 AND status = 'available'
          AND value = numerator / denominator
    ) THEN
        RAISE EXCEPTION 'Cash conversion did not apply the denominator rule at the requested duration';
    END IF;
END
$test$;
ROLLBACK TO loss_quarter;

SAVEPOINT invalid_assets;
UPDATE core.reported_facts
SET value = CASE concept WHEN 'total_assets' THEN 0 ELSE 4500000000 END
WHERE taxonomy = 'filing-statement-v1' AND accession = '0001024478-26-000048'
  AND concept IN ('total_assets', 'cash_and_equivalents');

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_borrowing_metrics('0001024478', DATE '2026-09-30', DATE '2026-11-12')
        WHERE metric = 'debt_to_assets' AND denominator = 0 AND status = 'nonpositive_denominator' AND value IS NULL
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_borrowing_metrics('0001024478', DATE '2026-09-30', DATE '2026-11-12')
        WHERE metric = 'net_borrowing_debt' AND status = 'available' AND value = -1224000000
    ) THEN
        RAISE EXCEPTION 'Borrowing metrics mishandled zero assets or negative net debt';
    END IF;
END
$test$;
ROLLBACK TO invalid_assets;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT accession, taxonomy, concept, unit, period_start, period_end, reporting_basis, scope_key,
       value + 1000000, reported_decimals, source_fetch_id, 'synthetic conflicting revenue'
FROM core.reported_facts
WHERE taxonomy = 'filing-statement-v1' AND accession = '0000049826-26-000049'
  AND concept = 'revenue' AND period_end = DATE '2026-06-30';

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_ratios(
            '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'ttm', DATE '2026-08-06'
        )
        WHERE metric = 'fcf_margin' AND status = 'conflicting_observations' AND value IS NULL
    ) THEN
        RAISE EXCEPTION 'A conflicting revenue observation did not suppress the trailing margin';
    END IF;
    RAISE NOTICE 'Financial ratio checks passed';
END
$test$;

ROLLBACK;
